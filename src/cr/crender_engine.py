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

"""CROWD_RENDER - return a subclass of the Blender RenderEngine class

Purpose

In order to have the crowdrender engine show up in the list of rendering
engines and to be able to render scenes, the crowdrender package has to 
subclass the RenderEngine class and define certain functions. The details
of which are located at the following URLs;

•   http://wiki.blender.org/index.php/Dev:2.6/Source/Render/RenderEngineAPI
•   http://www.blender.org/documentation/blender_python_api_2_57_release/
    bpy.types.RenderEngine.html

Classes Exported

Exceptions Raised

Functions Exported

"""

import bpy, time, zmq, sys, json, shutil, os, faulthandler, platform, inspect
from tempfile import TemporaryDirectory

from . import utils, ui_panels, render, rules
from . utils import MsgWrapper, handle_generic_except, setup_logging
from . utils import write_report_data_file
from statistics import mean
from math import floor
import uuid

####  CREATE CRASH LOGS #####
fault_text_file_path = os.path.expanduser("~") +\
     os.path.normpath("/cr/logging/crender_engine.txt")

if os.path.exists(fault_text_file_path):
    fault_text_file = open(fault_text_file_path, "wb")
else:
    utils.mkdir_p(os.path.split(fault_text_file_path)[0])
    fault_text_file = open(fault_text_file_path, "wb")

faulthandler.enable(file = fault_text_file)

## IMPORT ZMQ CONTEXT

s = os.path.sep

crowdrender = sys.modules[__package__]
zmq_context = crowdrender.zmq_context
x_buffer = render.denoising_xbuff
logger = setup_logging("RenderEngine")
temp_dir_obj = None#temporary directory used to store render results from nodes
# CONSTANTS

CHANNEL_IDS = 1 # #used in indexing to get the channels of render passes
NAME = 0 #used in indexing to get the name of render passes
CH_IDS = 0
CH_TYPE = 1
USE_PASS = 2
DEFAULT_PASSES = (
    'Combined', 
    'Depth',
    'Mist',
    'Normal',
    'Vector',
    'UV',
    'IndexOB',
    'IndexMA',
    'Shadow',
    'AO',
    'DiffDir',
    'DiffInd',
    'DiffCol',
    'GlossDir',
    'GlossInd',
    'GlossCol',
    'TransDir',
    'TransInd',
    'TransCol',
    'Emit',
    'Env') #used for testing if a pass is a standard pass (supported by 
            #blender's render engines, cycles and eevee

class CrenderEngine(bpy.types.RenderEngine):
    """Subclass of the Blender RenderEngine class.
    
    Documentation available for the bpy.types.RenderEngine class is here:
    http://www.blender.org/documentation/blender_python_api_2_68a_release/
    bpy.types.RenderEngine.html
    
    """
    
    
    bl_idname = crowdrender.package_name
    bl_label = 'Crowdrender'
    bl_use_postprocess = True
    bl_use_preview = False
    
        #bl_use_shading_nodes = True # Commented out due to issue where shading nodes gets
        # set when switching to our engine, even where we are sending a file with this
        # saved, the server session load the file with this flag false can causes a hash 
        # error. 
        
    def set_debug(self, addon_prefs):
        
        
        use_debug = addon_prefs.use_debug
        if use_debug:
            try:
                import pydevd
                pydevd.settrace('localhost', 
                                port=5678, 
                                stdoutToServer=True, 
                                stderrToServer=True,
                                    suspend=False)
            except ImportError:
            
                print("ImportError: Trying to import pydev for debugging")
                
            except:
                
                error = sys.exc_info()
                print("Unexpected error " + error[0] + " : " + error[1])
                
    def list_eevee_passes(self, scene, srl):
        
        non_eevee_passes = {
            'DiffInd',
            'GlossInd',
            'TransDir',
            'TransInd',
            'TransCol',
            'VolumeInd',
            'UV',
            'Vector',
            'IndexOB',
            'IndexMA',
            'Noisy Image',
            'Denoising Normal',
            }
        
        passes = []
        
        for name, channelids, channeltype in self.list_render_passes(
            scene, 
            srl):
            if name not in passes and name not in non_eevee_passes:
                passes.append((name, channelids, channeltype))
        
        #eevee specific
        eevee_passes = {
            "BloomCol":(
                "RGBA",
                'COLOR',
                getattr(srl.eevee, 'use_pass_bloom', False)
            ),
            "VolumeDir":(
                "RGBA",
                'COLOR',
                getattr(srl.eevee, 'use_pass_volume_direct', False)
            ),
             "VolumeScatterCol":(
                "RGBA",
                'COLOR',
                getattr(srl.eevee, 'use_pass_volume_scatter', False)
            ),
             "VolumeTransmCol":(
                "RGBA",
                'COLOR',
                getattr(srl.eevee, 'use_pass_volume_transmittance', False)
            )
            
        }
                #AOVS
        # Custom AOV passes.
        #aovs moved between 2.91 and 2.92
        aovs = getattr(
            srl, 
            'aovs', 
            getattr(
                srl.cycles, 'aovs', None)
        )
        
        for aov in aovs:
            if aov.type == 'VALUE':
                eevee_passes[aov.name] = (
                    "X",
                    'VALUE',
                    True)
            else:
                eevee_passes[aov.name] = (
                    "RGBA", 
                    'COLOR',
                    True)
        
        for name, r_pass in eevee_passes.items():
            if r_pass[USE_PASS]:
                passes.append(
                    (name,
                    r_pass[CH_IDS], 
                    r_pass[CH_TYPE]
                    )
                )
        
        return passes
        
                
    def register_eevee_passes(self, scene, srl):
        
        registered = set()
        #Default passes, same ones as cycles 
        for name, channelids, channeltype in self.list_eevee_passes(
            scene, 
            srl):
            if name not in registered:
                self.register_pass(
                    scene, 
                    srl, 
                    name, 
                    len(channelids), 
                    channelids, 
                    channeltype)
                
                registered.add(name)
    
    def list_render_passes(self, scene, view_layer):
        
        from cycles import engine
        
        # we need to distinguish between 2.83 and 2.91 which has a 
        # different calling convention, 2.83 only has one argument, the
        # srl
        signature = inspect.signature(engine.list_render_passes)
        
        args = {'scene':scene, 'srl':view_layer}
        
        if all(( arg in signature.parameters for arg in args)):
            
            return engine.list_render_passes(scene, view_layer)
        
        elif 'srl' in args:
            
            return engine.list_render_passes(view_layer)
        
    def update_render_passes(self, scene, srl):
        
        
        if  scene.crowd_render.render_engine == "BLENDER_EEVEE":
            
            self.register_eevee_passes(scene, srl)
            
        else:
            
            engine_modules = {
            eng_mod.bl_idname:eng_mod \
                for eng_mod in bpy.types.RenderEngine.__subclasses__()
                }
        #look for method to get panels 
            engine = engine_modules[scene.crowd_render.render_engine]
            
            update_r_passes = engine.update_render_passes
            
            update_r_passes(self, scene, srl)
            
        
    def handle_img_dwnld_prog(self, scene, msg):
        """ Update the upload progress for a node
        
        Arguments: 
            C:      bpy.context -   reference to context in blender
            msg:    MsgWrapper  -   crowdrender message wrapper object, must have:
                attributes = {
                        utils.node_uuid:        string  - unique id for the node
                        utils.percent_complete: int     - obvious!
                        utils.status:           int     - status code (should be -3, see
                                                                        utils.py)
                            }
        
        Returns:    
            None
            
        Side Effects:   
            Sets sync progress of the node identified by the uuid sent in the msg argument
            
        Exceptions:
            None
            
        Description:
            This method updates the percent uploaded figures that are visible to the
            user in the crowdrender panel. 
            
        
        """
        #get state of node and progresss
        node_state = msg.attributes.get(utils.status, None)
        dwnld_prog = msg.attributes.get(utils.percent_complete, None)
        
        #get ref to node
        cr_nodes = {node.node_uuid:node for node in scene.cr_nodes}
        
        node_uuid = msg.attributes.get(utils.node_uuid, None)
        
        try:
        
            if node_uuid is not None:
        
                node = cr_nodes[node_uuid]
            
                if node_state is not None and dwnld_prog is not None:
            
                
                
                    node.node_state = node_state
                    node.node_result_progress = floor(dwnld_prog)
                
                    #get ref to properties area if it exists and tag it for a redraw
                    for window in bpy.context.window_manager.windows:
                        for area in window.screen.areas:
                            if area.type == 'PROPERTIES': 
                                area.tag_redraw()
                
                else:
                    self.report({'WARNING'},"Node: " + str(node.name) +\
                        "update has bad state or progress")
            
            else:
                self.report({'WARNING'}, " Can't find: " + str(node_uuid) + "!")
                
        except:
        
            location = "CrenderEngine.handle_generic_except"
            
            log_string = "Caught an exception, continuing with render"
            
            handle_generic_except(location, log_string)
            
        return True
            
        
    def get_samples(self, scene):
        """ gets the number of per pixel samples associated with the render
        """
        
        engine = scene.crowd_render.render_engine
        
        if engine == 'CYCLES':
        
            if scene.cycles.progressive == "PATH":
            
                samples = scene.cycles.samples
                
            elif scene.cycles.progressive == "BRANCHED_PATH":
                
                samples = scene.cycles.aa_samples
                
            else:
                self.report({'ERROR'}, "Unrecognised sampling type: " +\
                     scene.cycles.progressive)
            
        elif engine == 'EEVEE':
            
            samples = 1
            
        elif engine == 'BLENDER_RENDER':
            
            samples = 1
            
        else:
            samples = 1
    
        return samples
        
    def get_manual_lb_values(self, scene):
        """ Returns a dictionary of manual load balance values
        
        """
        
        load_b_vals = {
            node.node_uuid:node.node_A_manual for name, node in scene.cr_nodes.items()
                                        }
        # Append the local
        load_b_vals.update({"local":scene.crowd_render.local_node.node_A_manual})
        
        
        return load_b_vals
    
    def update_st_prog(self, scene, msg):
        """ Upates the stats and progress bar during a render"""
        
        prop_area = None
        
        stats = msg.attributes[utils.render_stats]
        node_name = msg.attributes[utils.node_name]
        machine_uuid = msg.attributes[utils.machine_uuid]
        node_state = msg.attributes[utils.state]
        
        cr_nodes = {node.node_uuid:node for node in scene.cr_nodes}
        cr_nodes.update({'local':self.local_node})
        values = cr_nodes.values
        
        node = cr_nodes.get(machine_uuid)
        
        
        #get ref to properties area if it exists and tag it for a redraw
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'PROPERTIES':
                    prop_area = area
        
        if not node is None:
            
            try:
                
                node.node_state = node_state
        
                write_report_data_file(node.node_report_path, 
                        report_data = [stat[1] for stat in stats])
        
                for line in stats:
        
                    percent_complete = line[0]
                    render_stats = line[1]
        
                
                
                    self.update_stats(node_name, render_stats)
               
                    node.node_render_progress = round(percent_complete * 100)

                    
                    ## CALCULATE RENDER PROGRESS
                    # get the progress for each node and average it
                    r_node_progress = [node.node_render_progress\
                                    for node in values()\
                                    if node.node_state == utils.rendering]
            
                            
                    if len(r_node_progress) > 0:
                        progress = mean(r_node_progress)
                
            
                        self.update_progress(progress / 100.0)
            
                    #TODO: CR-347 - restore progress per node to be visible by the user
            
                    if prop_area is not None:
                        prop_area.tag_redraw()
        
                    rendering = True
            
            except:
                      
                location = "CrenderEngine.update_st_prog"
                log_string = "error detected during updating render status :"
            
                handle_generic_except(location, log_string, logger)
                  
                rendering = True
                        
        return rendering
    
    def create_temp_directory(self, S):
        """ creates a temporary directory for a render job, if one doesn't exist
        
        Arguments: 
            S - bpy.types.Scene
            
        Returns: 
            temp_dir_obj - string - the path of the temporary directory
        Notes:
            The creation of a temporary directory is done once per render job, 
            if that job is an animation, the temp location is only created
            once. The temp_dir_obj global variable is used to store the 
            TemporaryDirectory object, removing it or letting it go out of
            scope risks it being GC'd and the directory being removed. Not 
            something you'd want if you're rendering an animation
        
        """
        global temp_dir_obj
        
        if not os.path.exists(
            bpy.context.window_manager.cr.renderjob_temp_dir):
                
            session_path = bpy.context.window_manager.cr.session_path
            
            temp_dir_obj = TemporaryDirectory(dir = session_path)
            
            bpy.context.window_manager.cr.renderjob_temp_dir = temp_dir_obj.name
                
        return temp_dir_obj.name
        
        
    def setup_localhost_files(self, S, temp_blend_file):
        """ saves the blend file,for localhost rendering,if necessary"""
        
        if S.frame_current == S.frame_start and\
            S.crowd_render.local_node.node_render_active or\
            not self.is_animation:
                    
                bpy.ops.wm.save_as_mainfile(
                    filepath = temp_blend_file,
                    relative_remap = True,
                    copy = True
                     )
                    
        
    def render_command(self, S, temp_blend_file):
        """ Sends a command to the CIP to request a render from all nodes
        """
        C = bpy.context
        win_man = C.window_manager
        
        render_nodes = [n for n in S.cr_nodes]
        
        render_nodes.append(S.crowd_render.local_node)
        
        nodes = { node.node_uuid:
                    { 
                    utils.compute_devices:
                        [#list of this nodes compute devices
                            {# json object containing device data
                        'use':device.use,
                        'id':device.id,
                        'name':device.name,
                        'type':device.type
                            }
                         for device in node.compute_devices
                         ],
                    utils.compute_device:node.compute_device,
                    utils.tile_x:node.node_tile_x,
                    utils.tile_y:node.node_tile_y,
                    utils.process_threads:node.process_threads
                     }\
                 for node in render_nodes if node.node_render_active
                 }
        
        screen_resolutions = (S.render.resolution_x, S.render.resolution_y, 
                                S.render.resolution_percentage)
                                
        current_frame = S.frame_current
        img_output_fmt = utils.img_output_fmt
        
        #for each enabled view, send the view suffix and name so we make sure we
        # do not exit unless we've got all the views back loaded in blender.
        views = {view.file_suffix:view.name for view in C.scene.render.stereo_views\
                 if view.use and C.scene.render.use_multiview}
        
        sync_update_item = MsgWrapper(
            command = utils.render, 
            attributes = {
                utils.file_path:temp_blend_file, # use temp file instead of users
                                                            # file, lessens risk of file 
                                                            # handle conflicts
                utils.screen_res:screen_resolutions,
                utils.render_engine:S.crowd_render.render_engine,
                utils.current_frame:current_frame,
                utils.frame_range:(
                    S.frame_start, 
                    S.frame_end),
                utils.is_animation:self.is_animation,
                utils.img_output_fmt:img_output_fmt,
                utils.user_engine:S.crowd_render.render_engine,
                utils.eng_samples:self.get_samples(S),
                utils.manual_loadb:S.crowd_render.manual_load_balancer,
                utils.node_A_manual_values:self.get_manual_lb_values(S),
                utils.exr_codec:S.render.image_settings.exr_codec,
                utils.scene:S.name,
                utils.load_trusted:bpy.app.autoexec_fail,
                utils.nodes:nodes,
                utils.views:views
                        }
        )   
        
        self.cre_cip_dealer.send_string(
            json.dumps(sync_update_item.serialize(), 
            cls = utils.BTEncoder)
        )
    
#     def view_update(self, context):
#         
#         print("updated the data for view port rendering")
#         
#     def view_draw(self, context):
#         pass
        
    def frame_done(self, scene, msg):
        """ Returns True if all tiles have been received, False otherwise.
        
        The CIP will send a final msg when all tiles have been sent, there is a 
        check performed that makes sure all tiles were indeed received.
        
        Returns a boolean
        
        Side Effects: Sends a msg to the CIP to request tiles
        """
        
        #TODO: At some stage we need to check all tiles have been received
        # correctly. At present it's unnecessary to do so.       
        
        self.report({'INFO'}, "Finished frame: " + str(self.current_frame))
        print("Finished frame: ", self.current_frame)
        
        ret = False
        
        return ret
        
    def handle_recv_tile_fail(self, scene, msg):
        """ Handles the event of a file request for a tile failing
        
        Arguments:
            scene:      -   bpy.context.scene - current active context's scene object
            msg:        -   utils.MsgWrapper  - crowdrender message wrapper obj, must have
                attributes = {
                    utils.file_path: "file_path_failed_tile"
                    }
                    
        Returns:
            rendering:  boolean     Will pretty much be false since the loss of a render
                                    tile is pretty fatal to a frame. 
        """
        
        self.report({'WARNING'}," Failed to get a render tile!")
        
        rendering = False
        
        return rendering
        
    def handle_render_failed(self, scene, msg):
        """ Handle the case where a render node fails to render
        
        Arguments:
            msg - utils.MsgWrapper - message containing the error details, should contain:
                message - string - utils.render_failed
                t_uuid  - bytes  - unique id of the render task
                attributes - pydict - dictionary of attributes which should contain
                    {utils.error_message: string - contents of the error message}
        Returns:
            False - Boolean - the return value will be False to signal that this tile 
                is done. No point hanging around to 
        Side Effects:
            Updates the user interface with a warning to advise that a render node has
            failed to render. 
        Exceptions:
            None
        Description:
            This method handles the case where a node has an error during rendering, 
            typical errors for cycles are running out of RAM or asking the engine to 
            render an area that contains a dimension that resolves to less than one pixel
            in x or y dimensions. There are likely other error messages as well. The
            goal of this handler is to pass the message onto the user so that they have
            a chance to rectify the situation.
        """
        
        #Print to the user that there's been a problem
        self.report({'WARNING'}, "Render failed for " + msg.attributes[utils.node_name])
        
        print("Render Failed: ", msg.attributes)
        
        return False
    
    def add_eevee_passes(self, scene, rl=None):
        """ add eevee passes that aren;t the default"""
        
        if rl is None:
            raise RuntimeError("Render layer can't be null")
        
        for r_pass in self.list_eevee_passes(scene, rl):
            
            if r_pass[NAME] in DEFAULT_PASSES:
                continue
            else:
                self.add_pass(
                    r_pass[NAME], 
                    len(r_pass[CHANNEL_IDS]), 
                    r_pass[CHANNEL_IDS], 
                    layer=rl.name)
        
        
    def add_cycles_passes(self, scene, rl=None):
        """ Add the cycles render passes that aren't default.
        
        Tip, can only work if add passes once the render method in the RenderEngine
        class has been called."""
        
        
        
        if rl is None:
            raise RuntimeError("Render layer can't be null")
        
        #Use cycles own methods for listing the currently available passes, 
        # not exactly future proofing ourselves as cycles in blender 
        #officially has no API, but this at least makes us compatible with 
        # all cycle's passes.
        
        for r_pass in [
            r_pass for r_pass in self.list_render_passes(scene, rl)
            ]:
            
            if r_pass[NAME] in DEFAULT_PASSES:
                continue
            else:
                self.add_pass(
                    r_pass[NAME], 
                    len(r_pass[CHANNEL_IDS]), 
                    r_pass[CHANNEL_IDS], 
                    layer=rl.name)
                    
    
    def render(self, depsgraph):
        """ Main entry point for the render process
        
        This method is the main loop for the render engine class. It processes incoming
        messages and directs them to appropriate handlers which carry out the functions
        of updating stats and writing results of renders into blender's internal buffers.
        """
        global temp_dir_obj
        scene = depsgraph.scene
        scale = scene.render.resolution_percentage / 100.0
        self.size_x = int(scene.render.resolution_x * scale)
        self.size_y = int(scene.render.resolution_y * scale)
        context = bpy.context
        user_preferences = context.preferences
        addon_prefs = user_preferences.addons[
            crowdrender.package_name].preferences
        self.set_debug(addon_prefs)
        self.session_uuid = rules.get_session_uuid(bpy.data)
        self.local_node = scene.crowd_render.local_node
        self.start_port = addon_prefs.start_port
        self.port_range = addon_prefs.port_range
        
        ##SET DEBUG MODE
        #Start a remote debug session if this is set, or at least try to
        
        
        temp_dir_path = self.create_temp_directory(scene)
        
        temp_filename = bpy.data.filepath 
        
        if temp_filename == '': temp_filename = 'untitled.blend'
        temp_blend_file = os.path.join(temp_dir_path, temp_filename)
        self.setup_localhost_files(scene, temp_blend_file)
        ## NETWORK - setup socket to talk to the CIP directly (the CRMain operator is 
        # likely going to be disabled during a render.
        # The identity of the dealer socket has to be distinct to that of the cli_cip 
        # channel used normally, this is so that msgs meant for either channel can 
        # be distinguished. Also we recently noticed that msgs meant for a previous 
        # render on the same frame can penetrate a new render session for that frame
        # and corrupt the render. This has been averted by always salting the 
        # socket id with a uuid1 bytes object so that each render has a unique address
        
        if not hasattr(self, "cre_cip_dealer"):
            self.cre_cip_dealer = zmq_context.socket(zmq.DEALER)# old port 9999")
            self.cre_cip_dealer.setsockopt(
                zmq.IDENTITY, 
                bytes(
                    "".join([
                        self.session_uuid,
                        "_:" + "{0:0=4d}".format(scene.frame_current)
                    ]), 
                    'utf-8') + bytes(uuid.uuid1().hex, 'utf-8'))
            self.cre_cip_dealer.connect("tcp://127.0.0.1:" + str(self.start_port + 1))
            self.handlers = {
                utils.render_stats:self.update_st_prog,
                utils.result_ready:self.write_result,
                utils.view_ready:self.write_result,
                utils.finalise_render:self.frame_done,
                utils.recv_fail:self.handle_recv_tile_fail,
                utils.progress_update:self.handle_img_dwnld_prog,
                utils.render_failed:self.handle_render_failed
            }
        
        
        # self.cre_cip_dealer.send_json(ready_msg.serialize())
        # send command to the CIP so it can pass it to all nodes
        self.render_command(scene, temp_blend_file)
        
        ### ADD PASSES FOR CYCLES
        # Done here since after we send the command to render, we have time to run 
        # other scripts while the render nodes init and start their render. Better
        # to use this idle time on the client to setup the passes so we're not 
        # being inefficient. 
        if scene.crowd_render.render_engine == "CYCLES":
            
            self.add_cycles_passes(scene, depsgraph.view_layer_eval)
        
        elif scene.crowd_render.render_engine == 'BLENDER_EEVEE':
            
            self.add_eevee_passes(scene, depsgraph.view_layer_eval)
        
        self.current_frame = scene.frame_current
            
        rendering = True
        
        try:
            
            while rendering:
            
               
                if self.cre_cip_dealer.poll(20):
                    
                    msg_raw = self.cre_cip_dealer.recv_json(zmq.NOBLOCK)
                    
                    msg = MsgWrapper.deserialize(msg_raw)
                    
                    
                    handler = self.handlers.get(msg.command, 
                        self.handlers.get(msg.message))
                    
                    if not handler is None:
                        rendering = handler(scene, msg)
                                
                if self.test_break():
                        
                    #We're cancelling the render, need to send a cancel msg to the 
                    # CIP to get all nodes to stop. We have to send the session_uuid
                    # in this case since the local node won't respond in time before
                    # the render engine closes, resulting in the local's state not
                    # changing back to synced.
                    
                    
                    cancel_msg = MsgWrapper(command = utils.cancel_render,
                        s_uuid = bytes(self.session_uuid,'utf-8'),
                        attributes = {utils.message_uuid:str(uuid.uuid4())})
                    
                    self.cre_cip_dealer.send_json(cancel_msg.serialize())
                    
                    temp_dir_obj.cleanup()
                    
                    rendering = False
                    
        except:
            
            location = "CrenderEngine.render"
            log_string ="unknown error detected whilst attempting to render"
            
            handle_generic_except(location, log_string, logger)
            
            
            
        finally:
            #signal we've finished rendering
            if self.is_animation and scene.frame_current != scene.frame_end:
                pass
            else:
                
                temp_dir_obj.cleanup()
                
                #clean up sockets
                
            self.cre_cip_dealer.close(linger=0)
            
            del self.cre_cip_dealer
            
            print("finally finished rendering...")
            
        
        
        
        
    def write_result(self, scene, msg):
        """ Write the pixels from a finished tile to a render result
        
        This method writes the pixles from a file to the correct location 
        in the image and updates the screen to show the tile once its done.
        
        The method expects, as an argument, msg in a particular format  as follows: 
        
        msg.attributes =  {
        node_name = string, should be the name of the node that rendered this tile
        tile_coords = (X_0,  X_1,  Y_0,  Y_1), coordinates (floats) of the tile 
        layer_name = string
        pass_name = string
        tile_file_name = string
        frame_no = int
        }
        """
    
        import os
        
        from math import floor

        node_uuid = msg.attributes[utils.node_uuid]
        node_name = msg.attributes[utils.node_name]
        tile_coords = msg.attributes[utils.screen_coords]
#         layer_name = msg.attributes[utils.render_layer_name]
#         layer_name ="RenderLayer"
#         pass_name = msg.attributes[utils.render_pass_name]
        tile_file_name = msg.attributes[utils.file_path][1]
        frame_no = msg.attributes[utils.current_frame]
        rendered_view= msg.attributes[utils.view]
                
        # The node is finished so we mark it with the ready status
        cr_nodes = {node.node_uuid:node for node in scene.cr_nodes}
        
        node = cr_nodes.get(node_uuid)
        
        if node is not None:
            node.node_state = utils.ready
            node.node_result_progress = 0
            
        ## FIND FILE PATH FOR IMG RESULT
                 
        cr_path = utils.get_cr_path()
        
        scene = bpy.context.scene
        
        base_path = os.path.normpath(cr_path + '/' + self.session_uuid)
        
        
        file_ext = 'exr'    
        ### CALCULATE THE COORDINATES FOR THE IMAGE TILE###     
        
            
        if tile_coords[0] == 0.0:
            x_0 = 0
        else:
            x_0 = int(floor((tile_coords[0] + x_buffer / (2 * self.size_x)) *\
                self.size_x)) 
                 
        y_0 = int(floor(tile_coords[2] * self.size_y))
            
            
        x_1 = int(floor((tile_coords[1] - x_buffer / (2 * self.size_x)) *\
            self.size_x)) # overlap pixel for covering ourselves!
                 
        y_1 = int(floor(tile_coords[3] * self.size_y))
            
        w = x_1 - x_0
        h = y_1 - y_0
            
        current_frame = "{0:0=4d}".format(scene.frame_current)
        print("Current Frame is: " + current_frame)
        
        
        
        print("MACHINE UUID: ",node_name , "COORDS - X ", 
            x_0, ":", x_1, " Y ", y_0, ":",y_1)
                
        ### CREATE RESULT AND LOAD FROM FILE ###        
        result = self.begin_result(x_0, y_0, w, h, view=rendered_view)
        
        if not os.path.exists(tile_file_name): 
                
            #need to abort if any part of the image is missing
            self.report({'WARNING'}, "Could not find result image for :" +\
                            node_name)
            
            
            #errors here cause the whole render to cancel, even if one 
            # frame in an animation fails, probably want to improve this!
            self.end_result(result, cancel=True)
            
        else:
            
            #load pixel data from file into the render result
            result.load_from_file(tile_file_name)
            #update the pixels in the image editor so the tile is now visible
            self.update_result(result)
                
        
            self.end_result(result, do_merge_results=False)
        
        return True
#-------------------------END of CrenderEngine--------------------------------

def register():
    
    bpy.utils.register_class(CrenderEngine)
    
def unregister():
    
    bpy.utils.unregister_class(CrenderEngine)
    