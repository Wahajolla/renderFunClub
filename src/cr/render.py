############################  LICENSE  #########################
# <This software package is a plugin for Blender that uses the Crowdrender
# distributed rendering system.>
# Copyright (C) <2013-2021> Crowd Render Pty Limited, Sydney Australia
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# You can contact the creator of Crowdrender at info at
# crowdrender dot com dot au
################################################################

# <sort of PEP8 Compliant, lines are not always 79 chars long>

"""
render - module for handling rendering

Purpose

This module provides convenience functions for managing rendering. 

1. Interacting with processes that render, getting their output for stats
2. Recording performance for analysis and use in load balancing
3. Calculating screen space coordinates for each node during rendering



Modules Imported

Classes Exported
    CRRenderThread  - Class for extracting the output of the render process

Exceptions Raised

Functions Exported
    screen_divide   - calculates the optimal screen space coordinates for each node 
    scale_a         - Scales the screen area contributions of each node so that they sum
                         to one.


"""

## IMPORTS
import time, json, threading, zmq, subprocess, sys, os, faulthandler
from pprint import pprint
from random import randint, shuffle
from statistics import mean
from collections import deque
from math import floor

from . import config

from . utils import MsgWrapper, image_file_path, error_message, node_uuid, node_name
from . utils import render_stats, machine_uuid, output_buffer_size, finished_tile
from . utils import current_frame, t_s, k, render_failed, error_message, state, rendering
from . utils import synced, mkdir_p, timed_out, finished_view
from . utils import view, handle_generic_except
from . rules import get_blender_executable
from . config import read_config_file, write_config_file
from . logging import l_sep, setup_logging

####  CREATE CRASH LOGS #####
fault_text_file_path = os.path.expanduser("~") +\
     os.path.normpath("/cr/logging/render.txt")

if os.path.exists(fault_text_file_path):
    fault_text_file = open(fault_text_file_path, "wb")
else:
    mkdir_p(os.path.split(fault_text_file_path)[0])
    fault_text_file = open(fault_text_file_path, "wb")

faulthandler.enable(file = fault_text_file)

## CONSTANTS
denoising_xbuff = 0.0#12.0



class CRRenderThread(threading.Thread):
    
    def __init__(
            self, 
            t_uuid,
            node, 
            parent_th, 
            process, 
            frame_no,
            coords, 
            resolution,
            engine, 
            samples, 
            views={}
        ):
        
        threading.Thread.__init__(self, daemon= True)
        
        self.render_logger = setup_logging('render_logger_' + node.node_name)
        self.node = node
        self.parnt_thrd = parent_th
        self.process = process
        self.sock = self.parnt_thrd.context.socket(zmq.PUB)
        self.sock.connect("inproc://" + self.parnt_thrd.render_thread_sock_addr)
        self.line_buffer = list()
        self.numlines_to_buffer = output_buffer_size
        self.frame_no = frame_no
        self.frame_task_id = t_uuid
        self.coords = coords
        self.screen_res = resolution
        self.engine = engine
        self.samples = samples
        self.flush_timer = time.perf_counter()
        self.views = views
        
        self.start()
        
    def should_we_flush(self):
        """ Decide if we should flush, if yes call flush_to_sock, otherwise no nothing.
        
        the buffer of stats will only get flushed if we're due to give an update, or the
        requisite number of stats is ready to be sent. Otherwise we could waste bandwidth
        with too frequent updates, or, with no timeout, wait ages for an update if the
        buffer fills slowly up to the threshold amount of entries we've set to trigger
        the stats to update.
        
        This method also clears the line buffer as a side effect.
        """
        
        if self.line_buffer:
        
            if len(self.line_buffer) > self.numlines_to_buffer:
                self.flush_to_sock(self.line_buffer)
                self.line_buffer.clear()
                
            elif timed_out(self.flush_timer, 1.0): #wait up to 1 second before flushing
                #flush but also reset the timer
                self.flush_to_sock(self.line_buffer)
                self.flush_timer = time.perf_counter()
                self.line_buffer.clear()
        
        
    def run(self):
        
        img_tile_path = ''
        errors = []
        tile_rendered = False
        
        self.render_logger.info("CRRenderThread.run" + l_sep +\
             " rendering frame: " + str(self.frame_no) + " with coords: " +\
                 str(self.coords) )
        
        percent_complete = 0
        
        start_time = time.perf_counter()
        start_draw_time = 0.0
        rendering = True
        
        
        while rendering:
            
            if not self.proc_alive(): 
                self.render_logger.warning("Proc exited without rendeirng a tile")
                break
            #don't even attempt reading if the stream is closed
            
            
            try:
                self.process.stdout.flush()
                buf = self.process.stdout.readline()
            except:
                
                location= "CCRenderThread.run"
                message = "CRRenderThread.run:" +\
                         "error when trying read lines from stdout."
                
                handle_generic_except(location, message, self.render_logger)
                
            # no need to send null bytes. 
            if buf == b'': continue
            
            stats = buf.decode('utf-8').rstrip("\n").rstrip("\r")
            #msg_parts = stats.split(sep='|')
            #tiles = msg_parts[-1]
            
           
        #### CALCULATE THE PERCENTAGE COMPLETE FROM STAT OUTPUT ####
              
            # get the numerator and denominator for the number of parts/tiles complete
            if stats.rfind("Path Tracing Tile") > 0:
            
                # set start_draw_time only if it hasn't been set already.
                if start_draw_time == 0.0: start_draw_time = time.perf_counter()
                
                cycles_frac_comp = stats[ stats.rfind("Path Tracing Tile") +\
                    len("Path Tracing Tile") + 1:].split(',')[0]
                
                if cycles_frac_comp.find('/') > -1:
                    fraction_complete_parts = cycles_frac_comp.split('/')
                else:
                    fraction_complete_parts =""
                
                if len(fraction_complete_parts) == 2:
                    numerator = fraction_complete_parts[0]
                    denominator = fraction_complete_parts[1]
                    
                    
                    if numerator.isdigit() and denominator.isdigit():
                        percent_complete = int(numerator)/int(denominator)
                        
            elif stats.rfind("Path Tracing Sample") > 0:
            
                # set start_draw_time only if it hasn't been set already.
                if start_draw_time == 0.0: start_draw_time = time.perf_counter()
                
                cycles_frac_comp = stats[ stats.rfind("Path Tracing Sample") +\
                    len("Path Tracing Sample") + 1:].split(',')[0]
                
                if cycles_frac_comp.find('/') > -1:
                    fraction_complete_parts = cycles_frac_comp.split('/')
                else:
                    fraction_complete_parts =""
                
                if len(fraction_complete_parts) == 2:
                    numerator = fraction_complete_parts[0]
                    denominator = fraction_complete_parts[1]
                    
                    
                    if numerator.isdigit() and denominator.isdigit():
                        percent_complete = int(numerator)/int(denominator)
            
            elif stats.rfind("Rendered") > 0:
                if start_draw_time == 0.0: start_draw_time = time.perf_counter()
            
                cycles_frac_comp = stats[ stats.rfind("Rendered") +\
                    len("Rendered") + 1:].split(',')[0]
                
                if cycles_frac_comp.find('/') > -1:
                    fraction_complete_parts = cycles_frac_comp.split('/')
                else:
                    fraction_complete_parts =""
                
                if len(fraction_complete_parts) == 2:
                    numerator = fraction_complete_parts[0]
                    denominator = fraction_complete_parts[1].split(' ')[0]
                    
                    
                    if numerator.isdigit() and denominator.isdigit():
                        percent_complete = int(numerator)/int(denominator)
                        
            elif stats.rfind(", Part") > 0:
                
                # set start_draw_time only if it hasn't been set already.
                if start_draw_time == 0.0: start_draw_time = time.perf_counter()
                
                blend_int_comp = stats[ stats.rfind(", Part") +\
                        len(", Part") + 1:]
                
                if blend_int_comp.find('-') > -1:
                    fraction_complete_parts = blend_int_comp.split('-')
                else:
                    fraction_complete_parts =""
                
                if len(fraction_complete_parts) == 2:
                    numerator = fraction_complete_parts[0]
                    denominator = fraction_complete_parts[1]
                    
                    
                    if numerator.isdigit() and denominator.isdigit():
                        #blender render uses parts which are not
                        # always in order lowest to highest
                        percent_complete += 1/int(denominator)
            
            self.render_logger.info("CRRenderThread.run" + l_sep + " " +\
                buf.decode('utf-8').rstrip("\n"))           
            
            self.line_buffer.append([percent_complete, stats])
            
            
            #Detect whether we've reached the end of the render, the render process
            # will emit a "Saved" in its output buffer when this happens.
                            
            if 'Saved' in stats:
                
                tile_rendered = True
                
                self.flush_to_sock(self.line_buffer)
                self.line_buffer.clear()
                
                # self.node.last_render_time = time.perf_counter() - start_time
                # self.node.last_draw_time = time.perf_counter() - start_draw_time
                stop_time = time.perf_counter()
                render_time = stop_time - start_time
                draw_time = stop_time - start_draw_time
                setup_time = render_time - draw_time
                if setup_time < 0.0:
                    setup_time = 0.0
                
                session_uuid = self.node.session_uuid.decode('utf-8')
                
                #Calculate new k and t_s values and store them in conf
                conf_setup = read_config_file([config.node_perf_data])
                perf_data = conf_setup[config.node_perf_data].get(session_uuid)
                
                coords = self.coords
                A = (coords[1]-coords[0]) * (coords[3] - coords[2]) *\
                    (self.screen_res[0] * self.screen_res[1] *\
                    (self.screen_res[2] / 100) ** 2)
                    
                k_new =  draw_time / (A * self.samples) # k is seconds per pixel sample
                t_s_new = setup_time
                
                if perf_data is not None and isinstance(perf_data, dict):
                    # this is the case where we already have previous data for this
                    # session, though a different engine may have been used so 
                    # we may still end up adding a new entry for the particular engine
                    
                    eng_perf_data =\
                        conf_setup[config.node_perf_data][session_uuid].get(self.engine)
                    
                    #lets check to see if there is data for this engine, if not
                    # we'll add an entry for it.
                    if eng_perf_data:
                    
                        t_s_avg = mean([eng_perf_data[1], t_s_new])
                        k_all = deque(eng_perf_data[0], maxlen=25)
                        k_all.append(k_new)
                        k_avg = mean(k_all)
            
                        datum = [list(k_all), t_s_avg]
                        eng_perf_data = datum
                        
                        conf_setup[config.node_perf_data][session_uuid][self.engine] =\
                            datum
                        
                    else:
                        datum = [[k_new], t_s_new]
                        k_avg = mean([k_new]) 
                        conf_setup[config.node_perf_data][session_uuid][self.engine] =\
                            datum
                    
                    write_config_file(conf_setup)
            
                else:                    
                    #in the case where there is no data whatsoever for this
                    # node we'll simply create a new entry in the config file
                    # for it.
                    datum = [[k_new], t_s_new]
                    conf_setup[config.node_perf_data][session_uuid] =\
                        {self.engine:datum}
                    write_config_file(conf_setup)
                    k_avg = k_new
                    
                    
                
                #either we rendered one view of a tile or all of a tile
                # find out and act accordingly
                img_tile_path = stats.split('\'')[1]
                rendered_view = ''
                
                if self.views:
                    
                    while self.views:
                #remove the view we just rendered
                        
                                
                                
                        if len(self.views) > 1:#more views left to process, don't finalise render yet
                            
                            for file_suffix in self.views.copy():
                            #use the frame number and file ext name to match, just using the
                            # prefix is too coarse a method, users can edit the file suffix to be
                            # anything
                                if "{:0=4}".format(self.frame_no) + file_suffix + '.exr' in img_tile_path:
                                    rendered_view = self.views.pop(file_suffix)
                            
                            fin_view_msg = MsgWrapper(message = finished_view,
                                t_uuid = self.frame_task_id,
                                attributes = {image_file_path:img_tile_path,
                                            current_frame:self.frame_no,
                                            view:rendered_view,
                                            t_s:datum[1],
                                            k:k_avg #send just the avg not all data
                                            })
                            
                            self.sock.send_string(json.dumps(fin_view_msg.serialize()))
                            
                        else:
                            
                            for file_suffix in self.views.copy():
                            #use the frame number and file ext name to match, just using the
                            # prefix is too coarse a method, users can edit the file suffix to be
                            # anything
                                if "{:0=4}".format(self.frame_no) + file_suffix + '.exr' in img_tile_path:
                                    rendered_view = self.views.pop(file_suffix)
                            
                            fin_tile_msg = MsgWrapper(message = finished_tile,
                                t_uuid = self.frame_task_id,
                                attributes = {image_file_path:img_tile_path,
                                            current_frame:self.frame_no,
                                            view:rendered_view,
                                            t_s:datum[1],
                                            k:k_avg #send just the avg not all data
                                            })
                            
                            self.sock.send_string(json.dumps(fin_tile_msg.serialize()))
                            
                            rendering = False
                            
                            break
                            
                        buf = self.process.stdout.readline()
                        
                        if buf == b'':continue# don't process empty lines
                        
                        stats = buf.decode('utf-8').rstrip("\n").rstrip("\r")
                        if 'Saved' in stats:
                            img_tile_path = stats.split('\'')[1]
                        
                    
                
                   
                
                else:
                    fin_tile_msg = MsgWrapper(message = finished_tile,
                        t_uuid = self.frame_task_id,
                        attributes = {image_file_path:img_tile_path,
                                    current_frame:self.frame_no,
                                    view:rendered_view,
                                    t_s:datum[1],
                                    k:k_avg #send just the avg not all data
                                    })
                
                    self.sock.send_string(json.dumps(fin_tile_msg.serialize()))
                    
                    rendering = False
                    
                    break#finished the render no need to read any more output 
                    
                
            elif 'error' in stats or 'Error' in stats:
                #Errors can happen, some are fatal, some not, we're not going to 
                # abort the render, it may still finish and produce an image. 
                # We log this error and see if we can continue.
                
                #get the lines for the error
                #err_lines = str(self.process.communicate()) #no!
                
                err_str = "There was an error on " + self.node.node_name +\
                    "::" + stats 
                    
                errors.append(err_str)
               
                
            ## SEND BUFFER IS FULL - Send the stat buffer, avoids too much 
            # network chatter by sending blocks of the render stats rather than 
            # individual lines.
                
            
            self.should_we_flush()
                
                
        
        #if the render was successful we simply exit at this stage, but we log
        # any error msgs,
        if not tile_rendered:
            
            err_msg = MsgWrapper(message = render_failed,
                    t_uuid = self.frame_task_id,
                    attributes = {error_message:errors,
                                    node_uuid:self.node.machine_uuid,
                                    node_name:self.node.node_name,
                                    state:synced}
                                    )   
                                    
            self.sock.send_string(json.dumps(err_msg.serialize()))
        
        #otherwise we send an error msg and signal failed render tile
        else:
            
            #log errors if we had any, these must have been non fatal to the 
            # render process since we obtained an image
            if errors:
            
                err_string = ";".join(errors)
                self.render_logger.error("CRRenderThread.run" + l_sep +\
                    "errors detected whilst rendering" + err_string)
                
        self.render_logger.info("Closing RenderThread Socket")
        self.sock.disconnect("inproc://" + self.parnt_thrd.render_thread_sock_addr)
        self.sock.close(linger=0)
                    
                    
                
        ########        
    def flush_to_sock(self, buffer):
            
        
        
        update_msg = MsgWrapper(message = render_stats, 
            t_uuid = self.frame_task_id,
            attributes = {
            render_stats:buffer,
            node_name:self.node.node_name,
            machine_uuid:self.node.machine_uuid,
            state:rendering})
            
        self.sock.send_string(json.dumps(update_msg.serialize()))
            
        
        
    
    def proc_alive(self):
    
        res = self.process.poll()
        
        if res is None:
            return True
            
        else:
            return False
        
def create_render_process(trusted, coords, tile_x, tile_y, comp_dev, comp_devices,
                            threads, blend_file, output_path, engine, img_out_fmt, 
                            current_frame, exr_codec,
                            logger, scene_name):
    """ Create a process using Popen and return a reference to it
    
    Arguments:
        trusted         -   boolean - sets the -Y or -y option for blender's command line
        coords          -   tuple   - (xmin, xmax, ymin, ymax) screen coordinates to 
                                        render
        tile_x          -   int     - render tile size in pixels for x dim
        tile_y          -   int     - render tile size in pixels for y dim
        comp_dev        -   string  - enumeration in 'CPU', 'CUDA' 'OPENCL' denoting 
                                        the type of device being used
        comp_devices    -   py_dict - A collection of the render devices of the current 
                                    devices available
        blend_file      -   string  - path to the blend file to be opened for rendering
        output_path     -   string  - path to where the image file should be stored
        engine          -   string  - the render engine to be used
        img_out_fmt     -   string  - image format for the render, refer to blender's 
                                    documentation on the different image formats supported
        current_frame   -   int     - the frame number that will be rendered
        logger          -   logging.logger  - a reference to a current logging instance
    
    Returns:
        Subprocess.process
    Side Effects:
        Starts a separate process for use in rendering
    Exceptions Raised:
    
    Description:
        This function is a template function for creating a render process. It requires
        parameters for the render as given above in the arguments section which it then
        uses to configure the render process and launch it. The returned reference can 
        then be used to monitor the progress of the render through the output the 
        process normally gives via its stdout file handle.
    
    """ 

    if trusted:
            load_trusted = "-y"
    else:
        load_trusted = "-Y"
        
        
    import_string = "import bpy\n" +\
        "context = bpy.context\n" +\
        "scene = bpy.data.scenes['"+ scene_name +"']\n" +\
        "prefs = context.preferences.addons['cycles'].preferences\n" +\
        "prefs.get_devices()\n" +\
        "scene.render.use_border = True\n" +\
        "scene.render.use_crop_to_border = True\n" +\
        "scene.render.use_overwrite = True\n" +\
        "scene.render.border_min_x =" + str(coords[0])+"\n" +\
        "scene.render.border_max_x =" + str(coords[1])+"\n" +\
        "scene.render.border_min_y =" + str(coords[2])+"\n" +\
        "scene.render.border_max_y =" + str(coords[3])+"\n" +\
        "scene.render.use_compositing = False\n" +\
        "scene.render.use_sequencer = False\n" +\
        "scene.render.image_settings.exr_codec = \'"+ exr_codec +"\'\n"
        
    if tile_x > 7:
        import_string += "scene.render.tile_x = "+str(tile_x)+"\n"
    if tile_y > 7:
        import_string += "scene.render.tile_y = "+str(tile_y)+"\n"
        
    # Get devices for the requested device type 
    import_string+="devs= {d.id:d for d in prefs.get_devices_for_type(" +\
       "'" + comp_dev + "'" + ")}\n"
    #Turn off all devices so we clear the node's local preferences for devices
    import_string+="for dev in devs.values(): dev.use=False\n"
    
    #Handle GPU devices
    if comp_dev in ['OPENCL', 'CUDA', 'OPTIX']:
        
        import_string+="prefs.compute_device_type='"+ comp_dev + "'\n"
        import_string += "scene.cycles.device = 'GPU'\n"
        
        for item in comp_devices:
            #we only use devices that match the selected render device, but 
            # we also include CPUs since in cycles, they can be used in 
            # hybrid rendering with GPUs
            if item['type']==comp_dev:
            
                import_string+="device = devs.get('"+item['id']+"')\n"
                import_string+="if device is not None: device.use="+\
                                str(item['use'])+"\n"
        
    # handle CPU devices    
    elif comp_dev in ['CPU','NONE']:
    
        import_string+="prefs.compute_device_type='NONE'\n"
        import_string+= "scene.cycles.device = 'CPU'\n"
         
        for item in comp_devices:
            # again, only use devices that match the currently selected compute
            # devices (see cycles user preferences for the compute device setting).
            if item['type']==comp_dev:
                #We're using the CPU here since comp_dev is 'CPU', but we set
                # the actual value of the compute device to 'NONE' because this is
                # the correct setting for CPU rendering in blender cycles. 
               
                import_string+="device = devs.get('"+item['id']+"')\n"
                import_string+="if device is not None: device.use="+\
                                str(item['use'])+"\n"
                                
        
    
    #Re CR-779, we now use get_parent_executable to avoid
    # starting the wrong process
    
    exe_path = get_blender_executable()
    
    process = subprocess.Popen([
        exe_path, 
        "-b",
        "-noaudio", 
        blend_file,
        load_trusted,
        "-S", scene_name,
        "-o", output_path,
        "--python-expr", 
        import_string,
        "-E", engine,
        "-F", img_out_fmt,
        "-t", str(threads),
        "-f", str(current_frame),
        "--", "render_proc"
        ],
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT)

    return process
            
def calculate_optimal_render_area(machines, screen_x, screen_y, samples):
    """ Calculate the optimal screen area for each node based on their performance
    
    Arguments:
        machines    -   py_dict -   Collection of currently available render nodes
        screen_x    -   int     -   image resolution in x direction
        screen_y    -   int     -   image resolution in y direction
        samples     -   int     -   number of pixel samples that will be taken
    
    Returns:
        py_dict     {node_uuid - string - unique id for a render node : 
                            Ai - float - proportion of the
                                        total screen area that the node will render}
                                    
    Side Effects:
        None
    Exceptions Raised:
        None
    Description: 
        This method takes the stored performance data in each machine passed via the
        machines argument, and calculates firstly a To. To is an estimated optimum time
        that if all machines finish in, will be the fastest possible render time. It then
        uses this value to calculate the amount of screen area to give to each machine 
        so that it will finish in time To. 
        
        
    """
    
    ##### CALCULATE OPTIMAL RENDER TIME #######
    
    Ts = {uuid:machine.t_s for uuid, machine in machines.items()}
    K = {uuid:machine.k for uuid, machine in machines.items()}
    #This needs to use actual data for transit time
    Kx = {uuid:0.0 for uuid, machine in machines.items()} 
    
     #A is the total 'area' to be rendered, but we calculate area 
     # as the area in pixels multiplied by how many times each pixel is to 
     # be sampled. This value is then used in To, or optimal render time calculation
    A = screen_x * screen_y * samples
    
    
    sum_expr_1 = sum(
        list(map(lambda y, z: 1.0 / (y + z), Kx.values(), K.values())))
    sum_expr_2 = sum(
        list(
            map(
                lambda x, y, z: x / (y + z), 
                    Ts.values(), 
                    Kx.values(), 
                    K.values()
                )
            )
        )
    
    to  = A / sum_expr_1 + sum_expr_2 / sum_expr_1
    
    ##### CALCULATE NUM PIXELS FOR EACH NODE #######
    # We need this result to be a dimensionless fraction of the total screen area
    node_num_pix_columns = {uuid:
        int(round( 
            ((to - Ts[uuid]) / (Kx[uuid] + K[uuid]) / samples ) // screen_y))\
         for uuid in machines}
    
    node_pix_columns = [v for v in node_num_pix_columns.values()]
    
    diff = screen_x - sum(node_pix_columns)
    
    #We use diff as a 'bank' to make all nodes with 0 columns have 
    # at least one col, then start taking from the nodes with the most
    # cols until all nodes have at least one
    
    while diff or min([v for v in node_num_pix_columns.values()]) < 1:
        
        node_keys_sorted_by_pixel_cols = \
            [k for k, v in sorted(node_num_pix_columns.items(), 
                key= lambda item: item[1])]
        
        if diff > 0:
            
            diff -= 1
            
            node_num_pix_columns[node_keys_sorted_by_pixel_cols[0]] += 1 
            
            print("ADDING :", 1, " Pixel columns")
            
        elif diff < 0:
        
            diff += 1
            
            node_num_pix_columns[node_keys_sorted_by_pixel_cols[-1]] += 1 
            
        else:

            if node_num_pix_columns[node_keys_sorted_by_pixel_cols[0]] ==\
                node_num_pix_columns[node_keys_sorted_by_pixel_cols[-1]]:
                print("ERROR: hmmm, looks like something broke.")
                break
            else:
                #Robin hood protocol
                #take from larget & give to smallest
                node_num_pix_columns[node_keys_sorted_by_pixel_cols[-1]] -= 1
                node_num_pix_columns[node_keys_sorted_by_pixel_cols[0]] += 1
    
    return node_num_pix_columns
 
def screen_divide(machines, screen_x, screen_y, samples, manual_loadb, logger):
    """return screen coordinates (xmin, xmax, ymin, ymax) of n divisions
    
    Divides the screen into n sections and returns a list of tuples containing
    the screen coordinates of each section
    
    inputs:
    n - int: number of divisions the screen dimensions should be divided into
    screen_x - int: the screen dimension in the x direction
    screen_y - int: the screen dimension in the y direction
    """
    
    x_buffer = denoising_xbuff / screen_x
    num_machs = len(machines)
    
    
    # if the user has decided to set their own tuning of render tile sizes, then we 
    # don't calculate the A values for each node here, we simply load them from the 
    # user interface
    if manual_loadb:
        dict_num_pix = {uuid:
            node.node_A_manual * screen_x for uuid, node in machines.items()}
    else:
        dict_num_pix = calculate_optimal_render_area(
            machines, screen_x, screen_y, samples)
        
        #We here assign the values just calculated to each node so they're visible 
        # in the user interface.  
        for uuid, mach in machines.items():
            mach.node_A_auto = dict_num_pix[uuid]
                                                
    # TODO:JIRA:CR-57 this method of screen division only creates divisions in the
    # x axis, which means that the resulting divisions become very tall
    # and skinny as the number of nodes increases. Our testing that 
    # showed a quadratic relationship between division size and render
    # time used near square divisions. We will want to upgrade this later 
    # to create divisions vertically as well as horizontally.
    
    grid = [mac for mac in machines.values()]
    
    #we don't want to have the same machine draw the same part of the screen each time
    shuffle(grid)
    
    
    for i in range(0, len(grid)):
        
        machine = grid[i]
        x_columns = dict_num_pix[machine.machine_uuid]
        #DEBUG ONLY
        
        if i == 0: #first column ...
            
            x_min = 0.0
            #properly assign the entire screen if there is just one node
            if len(grid) == 1:
                x_max = 1.0
            else:
                x_max = (x_columns + 0.1) / screen_x + x_buffer
            y_min = 0.0
            y_max = 1.0
            
        elif i == len(grid) - 1:#last column, we make sure that x_max = 0
            
            x_min = grid[i - 1].screen_coords[1] - x_buffer
            x_max = 1.0
            y_min = 0
            y_max = 1.0
            
        else:#subsequent columns
            
            x_min = grid[i - 1].screen_coords[1] - x_buffer
            x_max = x_min + (x_columns + 0.1) / screen_x + x_buffer
            y_min = 0
            y_max = 1.0
        
        machine.screen_coords = (x_min, x_max, y_min, y_max)
        
        print("NODE: ",
              machine.node_name,
               " :",
              machine.machine_uuid, 
              "  screen coords: ", 
              machine.screen_coords)
        
    return machines
