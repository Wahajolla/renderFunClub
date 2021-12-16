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
ui_operators - define Blender operators

Purpose

This module subclasses the operators type of bpy.types.operators to
create custom operators that are triggered by the user. This typically
happens when the user presses the render button for example. We need to create
a hook that will react to this action by the user and trigger the right
part of our code. The way to do this is a custom operator that is 'tied' to
the render button.

There are many other actions that can be taken by the user that our code
needs to react to. Altering the render engine, changing render engine
settings all need to be director to our code and then acted on accordingly.

Input/Output

This module typically has no data input. It registers classes to be used
by blender as responders to button push events.


How

By subclassing the operator type of bpy.types, this module establishes
classes that can be registered. These registered classes are then linked to
events such as a button on the user interface being pressed. Simple as.

For more information on how this is done see:

http://wiki.blender.org/index.php/Dev:2.5/Py/Scripts/Cookbook/Code_snippets/Interface#Interface


Modules Imported

Classes Exported

Exceptions Raised

Functions Exported


"""


import bpy, sys, time, os, collections, json, uuid, subprocess, shutil, platform
from collections import deque

import zmq, threading, atexit
from . import utils, settings, rules, network_engine, hash_tree, ui_panels, config
from . import logging, settings
from . rules import get_blender_executable
from . utils import  last, dictionary, list_selected
from . utils import previously_selected_int, MsgWrapper, timed_out, states_user_sees
from . utils import func_time, profile_func, write_report_data_file
from . utils import handle_generic_except, setup_logging, get_base_app_version
from . utils import UploadTask
from . config import read_config_file, write_config_file
from . logging import l_sep
from . network_engine import PIPELINE
from bpy.props import BoolProperty, StringProperty
from tempfile import TemporaryDirectory



crowdrender = sys.modules[__package__]


### IMPORT ZMQ CONTEXT
# for packages with source code

s = os.path.sep

zmq_context = crowdrender.zmq_context

previously_selected = utils.previously_selected_int

from bpy.props import StringProperty, EnumProperty, CollectionProperty
from bpy.app.handlers import persistent

import faulthandler


####  CREATE CRASH LOGS #####
fault_text_file_path = os.path.expanduser("~") +\
     os.path.normpath("/cr/logging/operator_faults.txt")

if os.path.exists(fault_text_file_path):
    fault_text_file = open(fault_text_file_path, "wb")
else:
    utils.mkdir_p(os.path.split(fault_text_file_path)[0])
    fault_text_file = open(fault_text_file_path, "wb")

faulthandler.enable(file = fault_text_file)

CROWD_RENDER = crowdrender.package_name

### LOGGING
ui_ops_logger = setup_logging('blender_main', create_stream_hndlr = True, 
base_app = get_base_app_version())

### STRING CONSTANTS ###
data_object = 'data_object'
data_ptr = 'pointer'
item_uuid = 'item_uuid'
scene_ptr = 'scene'
operator = 'operator'
operator_ptr = 'operator_ptr'
upload_tasks = {}
#
EVENT_TIMER_DURATION = 0.032
### request bus
request_queue = deque()

### temporary copies of blend file for rendering
active_render = {}


def get_ip_failed_draw(self, context):

    self.layout.label(text = "Oops, we can't seem to find a network connection!",
                    icon = 'ERROR')
    self.layout.separator()
    self.layout.label(text = "please check your network connections and try again")

def trying_again_connect(self, context):

    self.layout.label(text = "Connection failed, trying again", icon = 'ERROR')

def connect_failed(self, contect):

    self.layout.label(text = "The attempt to connect ultimately failed, please check" +\
        " the node you wish to connect to is working and can be reached on the network",
        icon = 'ERROR')

def get_ip_success(self, context):

    self.layout.label(text = "success!",
                    icon = 'FILE_TICK')

def incorrect_engine(self, context):

    self.layout.label(text = "Please choose a render engine, like cycles or blender render")

def disconnected_machine(self, context):

    self.layout.label(text = "")

def resync_worked(self, context):

    self.layout.label(text = "Re-sync was successful!")

def resync_failed(self, context):

    self.layout.label(text = "Re-sync failed for some nodes")

def no_such_nodename(self, context):

    self.layout.label(text = "Oops, was expecting a node but" +\
        " on it connecting its no longer in the list?")

def unknown_error(self, context):

    self.layout.label(text = "Well thats a little embarressing, we were'nt expecting this. "+\
        "Feel free to try again, if the problem persists, contact us, see user prefs "+\
        " for information on how report this problem.")


def get_unique_name(name, C):
    """ Returns a unique name for a context.scene.cr_nodes item

    Arguments:
        name:   string      - the desired name
        C:      bpy.context - a reference to the active context in blender

    Returns:
        name:   string      - a unique name as determined by checking cr_nodes collection

    Side Effects:
        None

    Exceptions:
        None

    Description:

        This method searches for name in context.scene.cr_nodes. If the name already
        exists, then a new name is created by appending a number to the name as follows:

            name.001

        If such a name is requested, then the counter is simply incremented until a
        unique name is found.

    """

    name = "new node" #TODO: remove hardcoded string constant and use the conf file

    #Here we assure that the name will be unique, blender property collections
    # allow the same name to be used even where such collections behave like
    # dictionaries. When a status update returns from the CIP, we need to ensure
    # that we have a unique name for each node to avoid corrupting data.

    while name in C.scene.cr_nodes:

        if not '.' in name:

            root = name
            counter = "{0:0=3d}".format(1)

        else:
            root, counter = name.split('.')
            counter = int(counter)
            counter +=1
            counter = "{0:0=3d}".format(counter)

        name = root + '.' + counter

    return name

def get_temp_dir(parent_dir):
    """ Creates a temporary location for copies of the blend file
    
    Used for rendering and transferring a copy of the current state of 
    the user's project file, this method creates a temporary directory for 
    storage of the user's main blend file. Once the operation completes, however
    the temp file is discarded.
    
    
    """
    
    #create the temporary directory
    
    return TemporaryDirectory(dir = parent_dir)


class CRListDict(collections.UserList):
    """ A collection type that only allows in types with an 'as_pointer' attribute

    Description:
    This class combines a dictionary type with a list type with addition to the
    dictionary only where the item being added contains an 'as_pointer' attributed.

    This class has a special append method that appends a dictionary that will hold
    the appended item. It has a fileter that will only accept items with an as_pointer
    member.

    """

    def __init__(self, *args, **kwargs):

        super(CRListDict, self).__init__(self, *args, **kwargs)


    def append(self, value):
        """ Appends a structure like so (value, {value.as_pointer():value})


        """

        dictionary = {}

        if hasattr(value, '__iter__'):

            for v in value:

                if hasattr(v, 'as_pointer'):
                    dictionary[v.as_pointer()] = v
                else:
                    raise KeyError('CRListDict expected values with \'as_pointer\' attribute')

        else: raise TypeError('CRListDict expected value that is an iterable')

        super(CRListDict, self).append((value, dictionary))




class PackLogs(bpy.types.Operator):

    bl_idname = "crowdrender.log_file_package"
    bl_label = "Zip logs"
    bl_description = "Packages the log files in a zip format ready for sending"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filename: bpy.props.StringProperty(subtype="FILE_NAME")
    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        # setup default path and file name for reporting log files.
        self.directory = os.path.expanduser("~/Desktop")
        self.filename = "cr_log_" + utils.get_computer_name() + ".zip"
        
         #get paths for each file
        logging_path = logging.get_logging_path()

        #get sys-info
        sys_info_path = os.path.join(logging_path, 'host_sys_info.txt')

        #remove existing file so we don't keep adding them to the zip file each time :)
        if os.path.exists(sys_info_path):
            os.remove(sys_info_path)

        bpy.ops.wm.sysinfo(filepath = sys_info_path)

        fname=[sys_info_path]

        for (dirpath, dirname, fnames) in os.walk(logging_path):
            fnames.extend(fname)

        self.log_paths = [os.path.join(dirpath, f_name) for f_name in fnames\
             if not f_name in ('.DS_Store', 'logs_to_send.zip') ]

        print("about to pack following log files: ", self.log_paths)

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
        #pack files into an archive


        return self.execute(context)

    def modal(self, context, event):

        return {'RUNNING_MODAL'}

    def execute(self, context):
        from zipfile import ZipFile
        with ZipFile(os.path.join(self.filepath), mode='w') as log_zip:
            for log_file in self.log_paths:
                log_zip.write(log_file)
        return {'FINISHED'}

class open_issue_report(bpy.types.Operator):
    """ Open the crowdrender website
    """
    bl_idname = "crowdrender.report_issue"
    bl_label = "report an issue with the crowdrender addon"
    bl_description = "Opens a web browser to the crowdrender issue tracker"

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        return self.execute(context)

    def execute(self, context):

        import webbrowser

        webbrowser.open("https://www.crowd-render.com/report-a-problem", new=1)


        return {"FINISHED"}

class CRMain(bpy.types.Operator):

    bl_idname = "crowdrender.main"
    bl_label = "main entry point for host running blender interface"
    bl_description = "starts the crowdrender system"
    bl_options = {'REGISTER', 'INTERNAL'}
    temp_blend_file = ""


    ### CROWDRENDER VARS
    connections = {}
    key_sequence = deque()
    key_sequence_specials = deque()
    selected = CRListDict()
    saved_nodes = {}
    data_collections_updated = list()
    triggers = list()
    tasks = {}
    cip_alive = False #don't assume the cip is there until its been confirmed
    sip_alive = False #same as above :)

    ### EXPLICIT DATA BLOCK CHECKS
    # data blocks in this list need explicit checking as they are not associated with
    # blender's active_object and as a result won't be checked otherwise.

    root_uuid = '_BlendData::'

    ids_2_chk = ['_RenderSettings',
                 '_CyclesRenderSettings',
                 '_CyclesCurveRenderSettings'
                 ]


    
    logger = ui_ops_logger

    @classmethod
    def poll(cls, context):
        return True
        
    def create_report_file(self, node_uuid):
        """ Opens a text file in the temp directory of the session and returns the path
        
        
        """
        
        try:
            
            session_path = bpy.context.window_manager.cr.session_path
            
            path = os.path.join(session_path, node_uuid + "_report_data.txt")
            
            #only create the file is its not already there.
            if not os.path.exists(path):
            
                f = open(path, mode = "w")
                    
                path = f.name
        
                f.close()
            
        except:
            
            location = "CRMain.create_report_file"
            log_string =" could not open or write to report data file"
            
            handle_generic_except(location=location, log_string = log_string,
                logger = ui_ops_logger)
                    
        return path
        
    
    def before_save(self, *args):
        
        C = bpy.context
        
        cr = C.window_manager.cr
        
        ##CLEAR USER CREDENTIALS AND CREDIT
        # These values should never be stored in a blend file as blend files
        # can be shared online and would compromise an account.
        cr.password = ""
        cr.user_name = ""
        cr.cloud_credit = ""
        cr.num_cloud_insts_discovery = ""
        
        for S in bpy.data.scenes:
            
            cr_nodes = [node for node in S.cr_nodes]
            
            for node in cr_nodes:
                
                node.node_state = utils.null
                node.node_active = False
                
    
    def after_save(self, *args):
        """ Run after saving, request a refresh of node statuses
        """
        
        refresh_node_req = MsgWrapper(command = utils.update_node_status)
        
        request_queue.append(refresh_node_req)
        
        
    def timed_out(self, start, duration):
        """ return True if the requested period has expired, False otherwise
        """
        
        program_time_now = self.time_counter_coeff * self.time_counter
        
        return program_time_now - start > duration
    
    
    def invoke(self, context, event):
        
        self.time_counter_coeff = EVENT_TIMER_DURATION
        self.time_counter = 0
        ## DEBUG
        user_preferences = bpy.context.preferences
        
        addon_prefs = user_preferences.addons[crowdrender.package_name].preferences
        
        if addon_prefs.use_debug:
            
            try:
                
                ret = bpy.ops.preferences.addon_enable(module = "remote_debugger")
                
                if ret == {'CANCELLED'}:
                    print("remote debugger could not be enabled, is it installed?")
                    
                else:
                    ret = bpy.ops.debug.connect_debugger_pydev()
                    
                    if ret == {"CANCELLED"}:
                        print("remote debugger could not be enabled",
                            " the remote_debugger addon cancelled ",
                              "have you setup your path in user preferences?")
                        
            except:
                
                handle_generic_except("CRMain.invoke", "failed to init debugger")
                
        
        # Get ref to context
        C = context
        #toggle user engine choice to force update method on render_engine
        #property to be called, which updates the panels so blender 
        # shows relevant panels when crowdrender is the engine being used.
        user_engine_choice = C.scene.crowd_render.render_engine
        C.scene.crowd_render.render_engine = user_engine_choice
        #set local nodes names to local
        if type(bpy.data) is bpy.types.BlendData:        
            
            for s in bpy.data.scenes:
                s.crowd_render.local_node.name = "local"
        
        #create empty list of tasks, all that have gone before are now gone
        self.tasks = {}
        self.machine_uuid = utils.get_machine_uuid()
        
        # get a rules object
        self.rules = rules.CRRules()
        # set the data collections
        self.rebind_data_collections()
        
        self.user_engine = C.scene.render.engine
        
        self.use_persistent_data = C.scene.render.use_persistent_data
        
        self.keymaps_initialised = False #part of a hack to get addon to enable at start
        
        #attempt to set up keymaps, will try again in the modal loop if this fails here.
        if self.setup_keymaps(context):
            
            self.keymaps_initialised = True
        
        #self.set_session(context)
        # initialise crowdrender's data structures
        self.init_session(context, resyncing = False)
        
        #create mappings to our msg handlers
        self.map_msg_to_function()
        
        # create connections
        self.setup_network()
        
        bpy.app.handlers.save_pre.append(self.before_save)
        bpy.app.handlers.save_post.append(self.after_save)
        
        
        self.started = False #hack to deal with long file loads, though the invoke
                    # method is called from a handler on load_post, in true blender
                    # fashion, the load has not actually finished and the invoke 
                    # method is run before the load finishes, causing us to timeout
                    # any tasks we start in the invoke method, so we set this flag
                    # to false, then set it true once the modal handler starts and 
                    # us it to kick off our first init tasks that query if the CIP
                    # and SIP are running.
        
        # Add our selves as a modal handler to the current window.
        wm = context.window_manager
        wm.modal_handler_add(self)
        
        #TODO: remove hard coded values like this!
        self.timer = wm.event_timer_add(EVENT_TIMER_DURATION, 
                                        window = context.window)
        
        print("starting crowdrender...")
        
        
        return {'RUNNING_MODAL'}
    
    
    def modal(self, context, event):
        
        
        C = context
        
        
        if event.type == 'TIMER':
            
            
            self.time_counter += 1
            
            if self.started:
                
                self.process_msgs(context)
                
                self.process_async_tasks()
                
                if self.keymaps_initialised == False:
                    self.setup_keymaps(context)
                    
            else:
                #due to long loads, the hash_tree is created here, so that
                # we're reasonably assured that all data has been loaded. DOn't 
                # trus the load_post handler in blender.
                self._hash_tree = hash_tree.CRHashTree(bpy.data, self.rules)
                self.msg_queue = self._hash_tree.msg_queue
                
                        # See if our background processes are there, start them if not
                self.start_cip_task = self.add_async_task( (self.hello_cip, [],{}),
                                      (self.cip_process_start,[],{}), timeout=2.0
                                      )
                self.start_sip_task = self.add_async_task( (self.hello_sip, [],{}),
                                      (self.sip_process_start,[],{}), timeout=2.0
                                      )
                                      
                self.started= True
                
                
                
                print("STARTED CROWDRENDER")
                
        # process user input, but only once we've got background processes up
        # and running and a hash tree.
        elif self.user_action(context, event) and self.started:
            
            
            
            update_item = self.get_update(context)
            
            #self.detect_engine_change(C)
            
            undo_redo = self.is_undo_redo(update_item)
            
            if undo_redo:
                
                
                self.selected.clear()
                
                
                try:
                    
                    self.selected.append(C.selected_objects)
                    
                except:
                    
                    self.logger.warning("failed on adding active object to selected list")
                try:
                    
                    self.last_data_ptr = C.active_object.as_pointer()
                    
                except:
                    self.logger.warning(
                        "failed to get last data as pointer, deleted something?"
                            )
                    
                request_queue.append(undo_redo)
                
                refresh_node_req = MsgWrapper(command = utils.update_node_status)
                
        #        request_queue.append(update_blend_file)
                request_queue.append(refresh_node_req)  
                
            
            elif event.type == self.select_mouse:
                #Handle a new selection event
                
                if C.selected_objects != self.selected[last][0]:
                    self.selected.append(C.selected_objects)
                    
            
            else:
                
                if self.is_new_operator(update_item) and \
                                not update_item[operator] is None:
                    
                        bl_idname = update_item[operator].bl_idname
                        
                        if bl_idname in self.rules.op_handlers.keys():
                            
                            op_handler = self.rules.op_handlers[
                                            bl_idname
                                                                ]
                            
                            update = op_handler(self, update_item, C)
                            
                            # if the update succeeded then we should have an update
                            # to send to all nodes
                            if not update is None:
                                request_queue.append(update)
                                
                        else:
                            #TODO:JIRA:CR-53 decide if we'd rather deal with operators
                            # that merely transform existing data (like grab, rotate
                            # or scale when used modally) here or if there might
                            # be a better way.
                            
                            #self.logger.warning("unsupported operator used")
                            
                            self.process_nodes(update_item, C)
                
                else:
                    # This fork of the if statement checks to see if there
                    # have been any property modifications to the active object.
                    # This can happen where a user modifies an attribute of an object
                    # or mesh, such as a material setting.

                    # TODO:JIRA: CR-47, 43

                    self.process_nodes(update_item, C)

                #LESSON: copy is used instead of a straight assignment, since, for
                # lists (and other types that aren't simple types like str, int etc)
                # the assignment creates a link rather than copying which means
                # previously_selected will be updated instantly whenever selected is,
                # which entirely defeats the purpose!
        ui_panels.cr_running = True

        return {'PASS_THROUGH'}



    def execute(self, context):

        print("crowdrender modal handler exited")

        wm = context.window_manager

        wm.event_timer_remove(self.timer)


        return {'FINISHED'}

    def cancel(self, context):

        #wm = context.window_manager

        #wm.event_timer_remove(self.timer)

        self.cli_cip_dealer.close(linger =0)
        self.cli_sip_dealer.close(linger =0)

        self.tasks.clear()




    def map_msg_to_function(self):
        
        self.msg_map = {
            utils.hello_cip:self.init_cip,
            utils.hello_sip:self.init_sip,
            utils.ssp_alive:self.handle_new_node,
            utils.status_update:self.status_update,
            utils.progress_update:self.progress_update,
            utils.ext_report:self.ext_report,
            utils.discovery_refresh:self.handle_disc_req,
            utils.discovery_refresh_rental:self.handle_disc_rental_req,
            utils.discovery_login:self.handle_disc_login,
            utils.get_node_attrib_hashes:self.send_node_hashes,
            utils.get_nodes_by_uuid: self.send_nodes,
            utils.connect_failed:self.connect_node_failed,
            utils.repair_item:self.repair_item,
            utils.upload_task_complete:self.handle_upload_task_complete,
            utils.upload_task_begin:self.handle_upload_task_begin}
        
    def handle_upload_task_begin(self, C, msg):
        
        upload_task_fm_node = msg.attributes[utils.upload_task]
        files = upload_task_fm_node[1]
        node_uuid = msg.attributes[utils.node_uuid]
        upload_task = upload_tasks.get(upload_task_fm_node[0], None)
        
        if upload_task is not None:
            for file in files:
                upload_task.add_recipient(node_uuid, file)
    
    def handle_upload_task_complete(self, C, msg):
        
        upload_task_fm_node = msg.attributes[utils.upload_task]
        files = upload_task_fm_node[1]
        node_uuid = msg.attributes[utils.node_uuid]
        upload_task = upload_tasks.get(upload_task_fm_node[0], None)
        
        if upload_task is not None:
            for file in files:
                upload_task.update_task(node_uuid, file)
            
            if upload_task.is_finished:
                upload_tasks.pop(upload_task.upload_task_id)
                
        else:
            
            self.logger.warning("Received a completed upload task msg" +\
                " but the task was not found.")
    
    def add_async_task(self, action, timout_action, timeout=None):
        """ Adds an asynchronous task to the task list
        
        format required for a task is:
        action (func, [*args], {**kwargs})
        timeout_action (func, [*args], {**kwargs})
        
        
        """
        start = self.time_counter * self.time_counter_coeff 
        
        t_uuid = bytes(str(uuid.uuid4()),"utf-8")
        
        self.tasks[t_uuid] = (start, action, timout_action, timeout)
        # self.logger.debug("CRMain.add_async_task: " + l_sep +\
#             " A new task was added to the internal async tasks list : " +\
#             str(t_uuid))

        return t_uuid
    
    def task_report(self, t_uuid, *args, **kwargs):
        """ Wrapper for making Blender OT reports from the task system
        """
        
        self.report(*args)
    
    def ext_report(self, C, msg):
        
        type = msg.attributes[utils.message_type]
        message = msg.attributes[utils.message]
        args = [{type}, message]
        self.report(*args)
        
    
    def process_async_tasks(self):
        """ Processes tasks stored in a dictionary, tasks are removed once complete

        Format for a task
        {task_uuid:(start_time, (func, [*args], {**kwargs}), (func, [*args], {**kwargs})}


        """
        start_time = 0
        actn = 1
        actn_timeout = 2
        t_timeout = 3

        func = 0
        t_args = 1
        t_kwargs = 2

        #loop over a copy so we can remove tasks without raising an error
        tasks = self.tasks.copy()

        for t_uuid, task in tasks.items():

            # call the timeout task if we time out
            if self.timed_out(task[start_time], task[t_timeout]):

                task[actn_timeout][func](t_uuid,
                                        *task[actn_timeout][t_args],
                                        **task[actn_timeout][t_kwargs]
                                        )
                if t_uuid in self.tasks:
                    self.tasks.pop(t_uuid)
                else:
                    self.logger.warning("CRMain.process_async_tasks: " + l_sep+\
                        " Attempted to remove a task but it was no longer in the list"
                        )
                # self.logger.debug("CRMain.process_async_tasks: " + l_sep+\
#                     " Task :" + str(t_uuid) + "timed out: " + getattr(task[actn][func],
#                                                              '__qualname__', "?") +\
#                     " with args :" + str(task[actn][t_args]) + ":" +\
#                      str(task[actn][t_kwargs]))

            # otherwise continue to run the task
            else:
                try:
                    task[actn][func](t_uuid, *task[actn][t_args], **task[actn][t_kwargs])
                except:

                    location = "CRMain.process_async_tasks"

                    log_string = location + l_sep +\
                             " Task : " + str(t_uuid) + ":" + str(task) +\
                              " caused an exception."

                    utils.handle_generic_except(location, log_string, self.logger)




    def setup_network(self):
        """ Initialise network channels for crowdrender client process

    #######################################################################
    #The following definitions will aid understanding of the conn names
    #  cli  - Client Process (ie Blender Main Process)
    #  cip  - Client Interface Process (ie this process)
    #  sip  - Server Interface Process (on the local machine)
    #  ssp  - Server Session Process (on the local machine)
    #  sipr - Server Interface Process (on the remote machine)
    #  ssp - Server Session Process (on the remote machine)
    #######################################################################

    Connections used -

    cli_cip_dealer = dealer socket that connects this blend session to the
    crowdrender client interface process or CIP. Uses port 9001 with default ports
    or start_port + 1 if user customises the port ranges.

        """
        #                  GET PORTS
        #  Here we get the ports as specified by either the defaults or the
        # user's choice of a starting port and port number

        user_preferences = bpy.context.preferences
        addon_prefs = user_preferences.addons[crowdrender.package_name].preferences

        start_port = addon_prefs.start_port
        port_range = addon_prefs.port_range
        
        session_uuid = rules.get_session_uuid(bpy.data)

        self.cli_cip_dealer = zmq_context.socket(zmq.DEALER)
        self.cli_cip_dealer.setsockopt(zmq.IDENTITY, bytes(session_uuid, 'utf-8'))
        self.cli_cip_dealer.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.cli_cip_dealer.connect("tcp://127.0.0.1:" + str(start_port + 1))
        self.connections['cli_cip_dealer'] = self.cli_cip_dealer

        self.cli_sip_dealer = zmq_context.socket(zmq.DEALER)
        self.cli_sip_dealer.setsockopt(zmq.IDENTITY, bytes(session_uuid, 'utf-8'))
        self.cli_sip_dealer.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.cli_sip_dealer.connect("tcp://127.0.0.1:" + str(start_port + 2))
        self.connections['cli_sip_dealer'] = self.cli_sip_dealer

        self.logger.info("CRClient Network interfaces initialised")

    def cip_process_start(self, sess_uuid):
        """Starts  the Client interface and Server interface processes
        """
        import os
        # This call should really have error checking around it
        # since it attempts to open a file (cl_int_start.py).
        # There is a remote chance that a user could modify their
        # scripts location and not transfer our code meaning this
        # would fail.
        
        global client_interface_process
        
        exe_path = get_blender_executable()
        
        client_interface_process = subprocess.Popen(
            [exe_path, 
            "-b",
            "--factory-startup",
            "-noaudio",
            "-P",
            os.path.normpath(os.path.split(__file__)[0] + "/cl_int_start.py"),
            "--",
            "client_int_proc",
            ])#, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        client_interface_process.name = "client interface"

        # See if our background processes are there, start them if not
        self.start_cip_task = self.add_async_task( (self.hello_cip, [],{}),
                              (self.task_report,[{'INFO'},"Node manager ready"],{}),
                             timeout=10.0
                              )
        
        self.report({'INFO'},"Node manager starting...")

    def sip_process_start(self, sess_uuid):
        """ Start crowdrender server

        Arguments:
            sess_uuid:      bytes  -    the session unique id

        Returns:
            nothing
        Side Effects:
            starts the crowdrender server interface process
        Exceptions:
            none
        Description:
            Starts

        """

        global server_interface_process
            
        
        exe_path = get_blender_executable()
        
        server_interface_process = subprocess.Popen(
            [exe_path, 
            "-b",
            "-noaudio",
            "--factory-startup",
            "-P",
            os.path.normpath(os.path.split(__file__)[0] + "/serv_int_start.py"),
            "--",
            "-t",
            "server_int_proc",
            ])#, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        server_interface_process.name = "server interface"

        # See if our background processes are there, start them if not
        self.start_sip_task = self.add_async_task( (self.hello_sip, [],{}),
                              (self.task_report,[{'INFO'},"Render server ready"],{}),
                             timeout=10.0
                              )
        
        self.report({'INFO'},"Render server starting...")


        #End of process_start()

    def null_op(self, t_uuid):
        """ A null operation to use in situations where a null op is required

        Arguments:
            t_uuid:     string  -   a unique identifier used in the task system

        Returns:
            nothing

        Side Effects:
            None:

        Exceptions:
            None

        """
        pass

    def hello_cip(self, t_uuid):
        """ Hail the cip to check its there and if so ready the system
        """
                #keep polling the cip until its up.
        if not self.cip_alive:

            hello_msg = utils.MsgWrapper(command = utils.hello_cip, t_uuid = t_uuid)
            self.cli_cip_dealer.send_string(json.dumps(hello_msg.serialize()))


    def hello_sip(self, t_uuid):
        """ Hail the cip to check its there and if so ready the system
        """
                #keep polling the cip until its up.
        if not self.sip_alive:

            hello_msg = utils.MsgWrapper(command = utils.hello_sip, t_uuid = t_uuid)
            self.cli_sip_dealer.send_string(json.dumps(hello_msg.serialize()))

    def init_cip(self, C, msg):
        """ handler called when the CIP process responds to a hello msg
        """
        
        t_uuid = getattr(msg, 't_uuid', "")
        #only process valid tasks!
        if t_uuid in self.tasks:
            #only init CIP once!
            if not self.cip_alive:
            
                self.cip_alive = True
                self.logger.info("CIP is ALIVE")
                self.report({'INFO'}, "Connected to node manager")
                self.tasks.pop(msg.t_uuid)
                self.refresh_node_status(C)
                
                #update the user's credit from Blender Grid
                refr_credit_uuid = uuid.uuid4().int
                
                refr_credit_rqst = MsgWrapper( command = utils.updateUserCredit,
                    attributes = {utils._uuid:refr_credit_uuid})
        
                self.cli_cip_dealer.send_string(json.dumps(refr_credit_rqst.serialize()))
                # Request full refresh of nodes
                request_uuid = uuid.uuid4().int
        
                refr_rqst = MsgWrapper( command = utils.discovery_refresh,
                    attributes = {utils.on_complete:utils.discovery_refresh,
                        utils._uuid:request_uuid,
                        utils.blVersion:"_".join(map(str, bpy.app.version)),
                        utils.crVersion:"_".join(map(str, crowdrender.cr_version)),
                        utils.num_instances:C.window_manager.cr.num_cloud_instances})
        
                self.cli_cip_dealer.send_string(json.dumps(refr_rqst.serialize()))
                
                #request rental nodes, will be ignored if the user isn't actually
                # requesting, but needed so if they change files, the request
                # loop keeps going.
                request_rental_uuid = uuid.uuid4().int
                
                refr_rental_rqst = MsgWrapper( command = utils.discovery_refresh_rental,
                    attributes = {utils.on_complete:utils.discovery_refresh_rental,
                        utils._uuid:request_rental_uuid,
                        utils.blVersion:"_".join(map(str, bpy.app.version)),
                        utils.crVersion:"_".join(map(str, crowdrender.cr_version)),
                        utils.num_instances:C.window_manager.cr.num_cloud_instances})
        
                self.cli_cip_dealer.send_string(json.dumps(refr_rental_rqst.serialize()))
                
                self.logger.info("""sent refresh requests for user credit, node list and
                        rental instances""")
                
                self.report({"INFO"}, "Saving a temp copy of your file ")
                
                bpy.ops.crowdrender.initialise_cip(
                        'INVOKE_DEFAULT',
                        resync= False, 
                        load_trusted = not bpy.app.autoexec_fail,
                        top_hash = str(self._hash_tree.top_hash)
                        )
        else:
            
            self.logger.debug("CRMain.init_cip: " + l_sep +\
                    " a task with uuid: " + str(t_uuid) + " wasn't in the "+\
                    " task list when it was attempted to remove it")
            
        

    def init_sip(self, C, msg):
        """ Handler called when SIP process responds to a hello msg
        """
        
        t_uuid = getattr(msg, 't_uuid', "")
        #only process valid tasks!
        if t_uuid in self.tasks:
            #only init SIP once!
            if not self.sip_alive:
                self.sip_alive = True
                self.logger.info("SIP is AlIVE")
                self.report({'INFO'}, "Connected to render node server")
                self.tasks.pop(msg.t_uuid)
        else:
            self.logger.debug("CRMain.init_sip: " + l_sep +\
                " a task with uuid: " + str(t_uuid) + " wasn't in the "+\
                " task list when it was attempted to remove it")


    def process_msgs(self, context):


        if self.cip_alive:

            while request_queue.__len__():

                request = request_queue.pop()

                if request.command == utils.render:

                    self.user_engine = request.attributes[utils.user_engine]
                    self.persistent_images = request.attributes[utils.persistent_images]

                elif request.command == utils.resync:
                #If we're resyncing we need to send the current top_hash
                #until new hashing system is avilable, best strategy is to invalidate the
                # tree and reparse the host app's data.
                    self._hash_tree.parse_main(bpy.data, rebind=True)
                    
                    request.attributes[utils.top_hash] = self._hash_tree.top_hash
                #add the message uuid to guard against corruption on TCP retransmits

                request.attributes[utils.message_uuid] = str(uuid.uuid4())

                self.cli_cip_dealer.send_string(
                    json.dumps(request.serialize(),
                    cls = utils.BTEncoder)
                    )
                #self.logger.info(json.dumps(request.serialize(),
                #                cls= utils.BTEncoder))



        ######## RECEIVE MSGS FROM THE CIP AND CALL HANDLERS ################



        try:

            #for now, retain a message data block for each interface
            for conn in self.connections.values():


                if conn.poll(timeout=1):

                    # get more than one message, but no more than a maximum
                    # amount, this helps clear the incoming msg buffer under
                    # times of heavy usage, like when lots of machines
                    # are uploading
                    getting_msgs = PIPELINE
                    
                    while getting_msgs:
                        
                        getting_msgs -= 1
                        
                        con_message = utils.MsgWrapper.deserialize(
                            json.loads(
                            conn.recv_multipart(zmq.NOBLOCK)[0].decode('utf-8'),
                            object_hook = utils.as_BTObject))
                        
                        # if we received an alive msg then we need to respond back with a list
                        # servers we want to connect to.
                        if con_message.message in self.msg_map:
                            
                            
                            func = self.msg_map[con_message.message]
                            
                            func(context, con_message)
                            
                            #self.cli_cip_pubsub.send_string(json.dumps
                            
                        elif con_message.command in self.msg_map:
                            
                            func = self.msg_map[con_message.command]
                            
                            func(context, con_message)
                            
                            #self.cli_cip_pubsub.send_string(json.dumps
                            
        except zmq.ZMQError as e:
            
            if e.errno == zmq.EAGAIN: pass
            
        except:
            
            location = "CRMain.process_msgs"
            log_string = "Unknown error while attempting to recv message"
            
            handle_generic_except(location=location, log_string = log_string,
                        logger = ui_ops_logger)
            
            
        
        self.time_now = time.time()
    
    def setup_keymaps(self, C):
        
        ######    KEYMAP SETUP ###########################################################
        
        # setup access for keymaps so we know which keys are bound to important
        # triggers like select, action, grab, move, scale, etc, etc
        
        self.user_keymaps = C.window_manager.keyconfigs.active.keymaps
        
        
        if len(self.user_keymaps) < 1:
            ret = False
        else:
            
            try:
                
                select_mouse = C.window_manager.keyconfigs.active.preferences.select_mouse
            
                if select_mouse == 'RIGHT':
                    self.act_mouse = 'LEFTMOUSE'
                    self.select_mouse = 'RIGHTMOUSE'
                else:
                    self.act_mouse = 'RIGHTMOUSE'
                    self.select_mouse = 'LEFTMOUSE'

                keymaps = [('3D View','transform.translate'),
                 ('3D View','transform.rotate'),
                 ('3D View','transform.resize'),
                 ('Screen','ed.undo'),
                 ('Screen','ed.redo'),
                 ('Object Mode','object.delete'),
                 ('Object Mode','object.select_all'),
                  ('Window', 'wm.search_menu')]

                self.triggers = [self.user_keymaps[item[0]].keymap_items[item[1]].type \
                                for item in keymaps
                                ]

                self.triggers.append('MOUSEMOVE')
                self.triggers.append('NUMPAD_ENTER')
                self.triggers.extend([self.act_mouse, 'RET'])
                self.triggers.extend([self.select_mouse])

                select_all = self.user_keymaps['Object Mode'].\
                    keymap_items['object.select_all'].type

                self.triggers.extend(select_all)

                        #for undo/redo sequence
                if self.user_keymaps['Screen'].keymap_items['ed.undo'].oskey:
                    self.triggers.append('OSKEY')

                if self.user_keymaps['Screen'].keymap_items['ed.undo'].ctrl:
                    self.triggers.extend(['LEFT_CTRL', 'RIGHT_CTRL'])

                if self.user_keymaps['Screen'].keymap_items['ed.undo'].shift:
                    self.triggers.extend(['LEFT_SHIFT', 'RIGHT_SHIFT'])

                if self.user_keymaps['Screen'].keymap_items['ed.redo'].oskey:
                    self.triggers.extend('OSKEY')

                if self.user_keymaps['Screen'].keymap_items['ed.redo'].ctrl:
                    self.triggers.extend(['LEFT_CTRL', 'RIGHT_CTRL'])

                if self.user_keymaps['Screen'].keymap_items['ed.redo'].shift:
                    self.triggers.extend(['LEFT_SHIFT', 'RIGHT_SHIFT'])

                ret = True

            except:

                ret = False

        return ret


    def detect_bpy_data_ptr_change(self):
        """Returns True if the bpy.data pointer has changed, False otherwise
        """
        if self.bpy_data_ptr != bpy.data.as_pointer():

            self.bpy_data_ptr = bpy.data.as_pointer()

            if bpy.app.debug:
                print("UNDO or REDO operation")

            return True

        return False


    def is_undo_redo(self, update_item):
        """ Detects if an undo or redo happened
        """

        if self.detect_bpy_data_ptr_change():
            #Update the hash tree to recalculate hashes after an undo

            self.rebind_data_collections()

            undo_state = self._hash_tree.undo_history_change(bpy.data)

            if undo_state == -1: #then its an undo, create the approp
            # sync update giving the undo command
                self.logger.info("detected an undo")
                update_item[operator] = 'ED_OT_undo'
                result = self.rules._undo(self, update_item)

            elif undo_state == 1: #then its a redo, create the approp
            # sync update giving the redo command
                self.logger.info("detected a redo")
                update_item[operator] = 'ED_OT_redo'
                result = self.rules._redo(self, update_item)

            elif undo_state ==  0: # , then there was no difference,
            # there is no need to do anything
                self.logger.warning("undo query resulted in no state being found")
                result = None
            else:
                #log an error
                self.logger.warning("undo query resulted in an error, method did not return")
                result = None

        else:
            result = None

        return result

    def rebind_data_collections(self):

        D = bpy.data
        
        data_collections = ['armatures', 'brushes', 'cameras',
                                'curves', 'fonts', 'grease_pencils',
                                'collections', 'images', 'lights',
                                'lattices', 'libraries', 'linestyles',
                                'materials', 'meshes', 'metaballs',
                                'node_groups', 'objects', 'palettes',
                                'particles', 'scenes', 'texts',
                                'textures', 'worlds']

        self.data_collections = {
                    getattr(D, collection, None) for collection in data_collections
                                }

    def user_action(self, context, event):
        """ Determine if the user has entered a key stroke sequence signalling an edit.

        Args:

        context: bpy.context
        event: bpy.types.event

        Returns:

        boolean - true if the user pressed keys/mouse buttons indicating an edit,
            false otherwise.

        side-effects: modifies the class member key_sequence

        Description:

        This method attempts to discover if the user has potentially edited something in
        the scene. It does this by looking for key stroke sequences that match edits
        according to the current use keymap bindings (users might change these bindings
        and so we look up what they are rather than hard code).

        This method has some error associated with it, it will produce false positives
        as sometimes the user will just idly click somewhere which will return
        """

        if len(context.window_manager.operators):

            last_op = context.window_manager.operators[last]

            if last_op.bl_idname in rules.naughty_modals and\
               last_op.as_pointer() != self.last_select_op_ptr:
                #We need to detect if the last operator was a modal
                # operator that we aren't able to detect from
                # user inputs and handle them.

                bl_idname = last_op.bl_idname
                self.last_select_op_ptr = last_op.as_pointer()
                if bl_idname in self.rules.op_handlers.keys():

                    op_handler = self.rules.op_handlers[bl_idname]

                    update = op_handler(self, context)


        if event.type in self.triggers:


            #push this event to the deck
            if event.value == 'PRESS':

                self.key_sequence.append(event.type)
                #print("pushed an event on the deck ", self.key_sequence)
                result = False

            # process this event as a confirmation, but also prime for
            # a special case.
            elif event.value =='RELEASE':

                if len(self.key_sequence) > 0:

                    self.key_sequence_specials.extend(self.key_sequence)
                    self.key_sequence.clear()

                    result = True

                #Specials are where a trigger key is PRESSED and then
                # RELEASED which precedes another trigger key being
                # RELEASED that completes the action. We have to handle
                # this as a special case, in particular colour swatches
                # in Blender's interface cause this pattern.
                elif len(self.key_sequence_specials) > 0:

                    self.key_sequence_specials.clear()
                    self.key_sequence.clear()

                    result = True

                else:

                    result = False

            else:

                result = False




        elif event.type == 'ESC':
            self.key_sequence.clear()
            self.key_sequence_specials.clear()

            result = False

        else:

            result = False

        return result


    def get_update(self, C):
        """ Query active object and build and return an update object
        """
        update_item = {}

        update_item[utils.previously_selected] = list()
        update_item[utils.selected] = list()

        if len(self.selected) > 1:

            # update the list of all nodes that were previously selected
            last_selected_nodes = [self._hash_tree.nodes.get(obj_ptr).uuid \
                for obj_ptr in self.selected[previously_selected][dictionary].keys()\
                if obj_ptr in self._hash_tree.nodes]

            update_item[utils.previously_selected].extend(
                                                last_selected_nodes)

            if C.selected_objects != self.selected[last][list_selected]:
                self.selected.append(C.selected_objects)

        elif len(self.selected)>0:
            if C.selected_objects != self.selected[last][list_selected]:
                self.selected.append(C.selected_objects)

        else:
            self.selected.append(C.selected_objects)

        if C.active_object is not None:

            update_item[data_object] = C.active_object
            update_item[data_ptr] = C.active_object.as_pointer()

            node = self._hash_tree.nodes.get(update_item['pointer'])

            if node is not None:
                update_item[item_uuid] = node.uuid

            else:
                update_item[item_uuid] = ''

        else:
            update_item[data_object] = None
            update_item[data_ptr] = 0
            update_item[item_uuid] = ''


        if hasattr(C, 'active_operator'):

            if not C.active_operator is None:

                update_item[operator] = C.active_operator
                update_item[operator_ptr] = C.active_operator.as_pointer()

            else:

                update_item[operator] = None
                update_item[operator_ptr] = 0

        else:

            update_item[operator] = None
            update_item[operator_ptr] = 0

        return update_item


    def is_new_operator(self, update_item):
        """ return true if the operator is new, false otherwise

        This method is used to detect when a user has used a new operator to
        manipulate their scene.

        """

        # check to make sure we're not double handling operators. This can happen
        # after a render where operators like duplicate get run a second time, the
        # first part of the if statement catches these.

        if update_item[operator_ptr] == self.last_operator_ptr: return False

        # elif self.last_operator_ptr == update_item[operator_ptr]: return False


        else:

            self.last_operator_ptr = update_item[operator_ptr]

            return True

    def process_nodes(self, update_item, C):
        """ Find and re-process the CRHashTreeNode that has changed
        """

        node_updates = list()
        #TODO: BIIIG todo, should move this into the hash tree and create a proper API
        # to access the hash tree in a way that is simpler. At present a lot of
        # processing is done outside the tree that has to be done in a particular order
        # which is not great for outsiders to the project. E.g. to update the hash tree
        # takes at least four calls, it really should only take one.

        #Request that the hash tree update itself using the active_objects
        node_updates = []
        node_updates.append(self._hash_tree.update_node(False,
            node_pointer = update_item[data_ptr]))


        #List comprehensions are weird and don't apparently have access to variables
        # created in their parent functions scope. They do however have access to global
        # variables and apparently variables passed to the function.
        # The rules for what they can access seems arbitrary to me and appears to have
        # been done because people are too stupid to rename an iterator variable to avoid
        # bleeding.

        if C.scene.world:
            #deal with world ID block in use here
            world_id = self.root_uuid + C.scene.name + '_Scene::' +\
             C.scene.world.name + "_World"

            scene_id_blocks_checked = [world_id]
        else:
            scene_id_blocks_checked =[]



        scene_id_blocks_checked.extend(
            [self.root_uuid + C.scene.name + '_Scene::' + id_block\
                            for id_block in self.ids_2_chk\
                            if self.root_uuid + C.scene.name +\
                                '_Scene::'+ id_block in self._hash_tree.nodes_by_uuid])
        
        #update cycles view layer settings if they have changed
        scene_id_blocks_checked.extend(    
            [self.root_uuid + C.scene.name + '_Scene::' + layer.name + "_ViewLayer"\
                for layer in C.scene.view_layers\
            if self.root_uuid + C.scene.name + '_Scene::' + layer.name + "_ViewLayer" in\
                self._hash_tree.nodes_by_uuid]
                                        )



        for id in scene_id_blocks_checked:
            x = self._hash_tree.update_node(False, node_uuid = id)
            if x != []:
                node_updates.append(x)

        # get all non zero lists of nodes and flatten them into one long list of 
        # every node that needs to be updated.
        
        updates = []
        
        for upd_list in node_updates:
            
            if upd_list[0]: updates.extend(upd_list[0]) 
        
        #Create a manifest of all the nodes that we'll be syncing
        sync_manifest = {
                    node.get(utils.node_uuid):
                    {
                        utils.attributes:node.get(utils.attributes,None),
                        utils.value:node.get(utils.value,None)
                    
                    } for node in updates
                        }
        
        if len(sync_manifest) > 0:
        
            update = utils.MsgWrapper(command = utils.data_update,
                        attributes = {
                        utils.top_hash:self._hash_tree.top_hash,
                        utils.scene:C.scene.name,
                        utils.sync_manifest:sync_manifest
                                    })

            request_queue.append(update)

                



    def tag_redraw(self, context):
        """ tags the area containing crowdrender's panel for redrawing

        This method inspects the ui in blender to find the render properties
        panel if it exists. If it does then it tags the properties panel to be
        redrawn. This is used for updating our panel when there are changes to
        be displayed to the user.
        """
        if context.area is not None:

            if context.area.type == 'PROPERTIES':
                context.area.tag_redraw()


        else:

            screens = [window.screen for window in context.window_manager.windows]

            sc_areas = []

            areas = [sc_areas.extend(screen.areas) for screen in screens ]

            prop_area = [area for area in sc_areas if area is not None and area.type == 'PROPERTIES']

            for area in prop_area:
                area.tag_redraw()
            # map(lambda area: area.tag_redraw(), prop_area)


    def set_session_uuid(self, C):
        # if we are loading a file we check to see if there is a crowd_render
        # property set, we then check to see if there is a session id
        # if so then we can load it, otherwise we create one
        
        session_uuid = rules.get_session_uuid(bpy.data)
        
        if not session_uuid:
            
            rules.create_session_uuid()
        
        self.cr_path = utils.get_cr_path()
        

    def refresh_node_status(self, C):
        """ ensure that all nodes are loaded with the correct state on init session

        This method checks each node against the machines collection of client. If there
        is a mismatch in the state or if the node doesn't exist in the machines collection
        the node is assigned a null status. This prevents files from loading and then
        displaying nodes as if they had a status other than null, which is of course
        totally wrong.

        """

        #use not for autoexec_fail since we're actuall after the state of "load trusted"
        # which is the opposite to autoexec_fail

        for node in C.scene.cr_nodes:
            node.node_state = utils.null

        refresh_node_req = MsgWrapper(command = utils.update_node_status)


        request_queue.append(refresh_node_req)


        


    def init_session(self, C, resyncing = False, load_trusted = False):
        """ Initialise all data required for a new session
        """

        import os

        #this is a bit of a hack required under the current
        # track_scene_update era. We need to ensure we don't
        # constantly call init_session so we need a bool
        # flag to signal that we're currently doing
        # an init.
        # self.initialising = True
        # Ensure all nodes have their status value checked against the machines
        # collection. Stops the nodes being loaded with the wrong status.
        
        
        self.last_select_op_ptr = 0
        
        # need to do a nested getattr as 2.8 doesn't have the same attribute for
        # the render engine as 2.79 and prev did.
        
        try:
            render_settings = getattr(C.scene,'render',
                                    getattr(C.scene, 'view_render', ""))
            
            self.r_engine_selected = render_settings.engine
            
        except AttributeError:
            
            self.logger.warning("Could not get a reference to the render settings")
            self.report({'ERROR'}, "Could not get a reference to the render settings")
            
        self.bpy_data_ptr = bpy.data.as_pointer()
        
        
        #Add a reference to the object currently selected
        
        self.selected.clear()
        self.selected.append(C.selected_objects)
        
        active_obj = getattr(C, 'active_object')
        active_op = getattr(C, 'active_operator')
        
        if active_obj is not None:
            self.last_data_ptr = active_obj.as_pointer()
        else:
            self.last_data_ptr = 0
            
        if active_op is not None:
            self.last_operator_ptr = active_op.as_pointer()
        else:
            self.last_operator_ptr = 0
            
        if not resyncing: self.completed_operators = {}
        
         #set up the CRSession object
        self.set_session_uuid(C)
        
        self.temp_dir = TemporaryDirectory(dir = self.cr_path)
        
        blend_file_name = os.path.basename(bpy.data.filepath)
        
        if not blend_file_name: blend_file_name = 'untitled.blend'
        
        session_path = self.temp_dir.name
        
        C.window_manager.cr.temp_blend_file = os.path.join(session_path, blend_file_name)
        
        C.window_manager.cr.session_path = session_path
        
        #Need to check whether this is a new session or not.
        
        
        #TODO:JIRA:CR-38:sub 1: clearly when initialising a session which has a list of stored
        # servers, we'd either send that list from here or load it from the
        # client interface process.
        
        #use not for autoexec_fail since we're actuall after the state of "load trusted"
        # which is the opposite to autoexec_fail
        
    def refresh_discovery_rental(self, t_uuid, refresh_interval):
        """ starts another iteration of the rental request loop in CR
        
        Arguments:
            t_uuid:             string  -   unique id used for indexing this task in
                                            the task system
            refresh_interval:   float   -   timeout in seconds after which to refresh
                                            the list of render nodes

        Returns:
            nothing

        Side Effects:
            Causes the CIP to request either a refresh of the users's data or refresh
            the data and request cloud nodes.

        Exceptions:
            none

        Description:
            this method forms part of a loop who's purpose is to periodically make a
            request to the discovery server for BG instances. The aim of this method
            is to make sure if the client requesting the nodes dies, that the BG 
            instances eventually shut down, since the request loop stops and so do
            the instances. This stops the user getting charged if their client dies 
            overnight and they are not aware of it. 
            
            
        """



        C = bpy.context
        request_uuid = uuid.uuid4().int
        credit_refresh_uuid = uuid.uuid4().int


        command = utils.discovery_refresh_rental
        handler = utils.discovery_refresh_rental
        #Prepare the response that will be a heartbeat
        resp = MsgWrapper( command = command,
            attributes = {utils.on_complete:handler,
                utils._uuid:request_uuid,
                utils.blVersion:"_".join(map(str, bpy.app.version)),
                utils.crVersion:"_".join(map(str, crowdrender.cr_version)),
                utils.num_instances:C.window_manager.cr.num_cloud_instances})
                
        cred_refr = MsgWrapper( command = utils.updateUserCredit,
            attributes ={utils._uuid:credit_refresh_uuid})
            
        self.cli_cip_dealer.send_string(json.dumps(cred_refr.serialize()))

        self.cli_cip_dealer.send_string(json.dumps(resp.serialize()))
    

    def refresh_discovery(self, t_uuid, refresh_interval):
        """ Call for a refresh of the nodes list in discovery

        Arguments:
            t_uuid:             string  -   unique id used for indexing this task in
                                            the task system
            refresh_interval:   float   -   timeout in seconds after which to refresh
                                            the list of render nodes

        Returns:
            nothing

        Side Effects:
            Causes the CIP to request either a refresh of the users's data or refresh
            the data and request cloud nodes.

        Exceptions:
            none

        Description:
            this method forms part of a loop. The user needs to have a constantly up to
            date list of all render nodes available to them. A request made to the
            CIP causes it to query the discovery server, the result is returned in such
            a manner as to 'request' that the blender main process respond with another
            request. This ensures that if the blender main process crashes, then the CIP
            will stop requesting nodes and any cloud instances will shut down. It ensures
            that the user doesn't get charged if there is a crash in blender.
        """



        C = bpy.context
        request_uuid = uuid.uuid4().int


        command = utils.discovery_refresh
        handler = utils.discovery_refresh
        #Prepare the response that will be a heartbeat
        resp = MsgWrapper( command = command,
            attributes = {utils.on_complete:handler,
                utils._uuid:request_uuid,
                utils.blVersion:"_".join(map(str, bpy.app.version)),
                utils.crVersion:"_".join(map(str, crowdrender.cr_version)),
                utils.num_instances:C.window_manager.cr.num_cloud_instances})

        self.cli_cip_dealer.send_string(json.dumps(resp.serialize()))

    def handle_disc_login(self, C, msg):
        """ Handle the result of an attempt to login to discovery

        Arguments:
            Context:    -   bpy.context object
            MsgWrapper: -   Crowdrender MsgWrapper object, Must contain:

        Returns:
            nothing
        Side Effects:
            Displays the result of the login attempt to the user, if the attempt was
            successful, write the token obtained to the config file for future use.

        Exceptions:

        Description:

        """
        logged_in = msg.attributes.get(utils.logged_in, None)

        if logged_in:

            ##SUCCESS!
            # The user is logged in, set the token and display welcome message'
            self.report({'INFO'}, "Successful Login to Crowdrender!")
            C.window_manager.cr.logged_in = True

            self.refresh_discovery("", 1.0)

            self.tag_redraw(C)




        else:

            ## FAILURE !
            # uhoh, the user might have entered a bad passw or username, in either
            # case we respond with a failed msg and offer another attempt.
            self.report({'WARNING'}, " Login failed, please check username/password")

    def handle_disc_rental_req(self, C, msg):
        """ Handle reception of response to a rental request
        
        Arguments:
            Context:   -    bpy.context object
            MsgWrapper -    Crowdrender MsgWrapper object, Must contain:
                attributes = {utils.request_response:
                                { "data": {"machines":{"computerName":string,
                                                        "active":boolean,
                                                        "accessKey":string,
                                                        "local":boolean,
                                                        "machineData":{
                                                            "crVersion":string
                                                            "blenderVersion":string
                                                            "renderDevices":[]
                                                                }
                                                        }
                                            }
                                }
                            }

        Returns:
            nothing

        Side Effects:
            Sends a MsgWrapper object to the CIP as a heartbeat

        Exceptions:
            None

        Description:
            This method handles the response to a request for BG instances. It is part
            of a separate request loop to discovery. It only mutates the user's account
            to ask for rental instances, it does not request user data.
        
        
        """
        
        network_timeout_dflt = read_config_file(
                        [config.network_timeout]
                                            )[config.network_timeout]*1000

        refresh_interval= network_timeout_dflt
        
        cr = C.window_manager.cr
        
        if not type(msg.attributes[utils.request_response]) is dict:
            self.logger.warning("CRMain.handle_disc_req: "  + l_sep +\
                " got a response that wasn't in the correct format :" +\
                str(msg.attributes[utils.request_response]))
        else:

            #set boolean to show user we're requesting now
            ui_panels.cr_requesting = msg.attributes[utils.requesting]

            data = msg.attributes[utils.request_response].get(utils.data)
            
            if data is not None: 
                req_data = data.get(utils.requestRentalInstances, None)
                if req_data is not None: 
                    refresh_interval = req_data.get(utils.refreshInterval, 30000)
            
            error = msg.attributes[utils.request_response].get(utils.error)
            errors = msg.attributes[utils.request_response].get(utils.errors)
            logged_in = msg.attributes.get(utils.logged_in, None)
            
            if not logged_in is None:
                cr.logged_in = logged_in

            if errors is not None:
                for err in errors:
                    error_message = err.get('message')
                    # add this error message to the list of msgs for cloud
                    bpy.ops.crowdrender.add_cloud_issue("INVOKE_DEFAULT", 
                                err_text = error_message)
                    # 
                    # bpy.ops.crowdrender.show_discovery_error('INVOKE_DEFAULT', 
#                         err_text=error_message)    

            if error is not None:

                if error == utils.auth_required:
                    cr.logged_in = False
                    cr.cloud_credit = ""

                    ##RETURN EARLY
                    #need to return early here and not request again until the
                    # user logs in.

                    return
                    
        self.add_async_task(
            (self.null_op, [], {}),
            (self.refresh_discovery_rental,
            [refresh_interval/1000], {}), #/1000 cause its given in milliseconds
            timeout=refresh_interval/1000 * 1.1)

        self.tag_redraw(C)    
        

    
    def handle_disc_req(self, C, msg):
        """ Handle an event where a request to the discovery server returns a node list

        Arguments:
            Context:   -    bpy.context object
            MsgWrapper -    Crowdrender MsgWrapper object, Must contain:
                attributes = {utils.request_response:
                                { "data": {"machines":{"computerName":string,
                                                        "active":boolean,
                                                        "accessKey":string,
                                                        "local":boolean,
                                                        "machineData":{
                                                            "crVersion":string
                                                            "blenderVersion":string
                                                            "renderDevices":[]
                                                                }
                                                        }
                                            }
                                }
                            }

        Returns:
            nothing

        Side Effects:
            Sends a MsgWrapper object to the CIP as a heartbeat

        Exceptions:
            None

        Description:
            The purpose of this method is two fold. First, it handles the event of a
        response to the CIP making a request to discovery for the active node list.
        Second, it acts as a heartbeat to keep the CIP request from dying. Each time
        the method is run, it will send a response. So as long as there is an active
        session that the user can benefit from the CIP will keep any cloud nodes alive.
        As soon as the heartbeats stop, the CIP will stop requesting cloud nodes.
        This is an important failsafe to stop the cloud nodes from being kept alive
        after the user has stopped using them.

        """


        network_timeout_dflt = read_config_file(
                        [config.network_timeout]
                                            )[config.network_timeout]*1000

        refresh_interval= network_timeout_dflt

        node_list = None
        cr = C.window_manager.cr

        ## EXTRACT NODE DATA FROM RESPONSE
        # we check if the response is a dict as sometimes we can get just
        # a string, esp if the request to the server times out

        if not type(msg.attributes[utils.request_response]) is dict:
            self.logger.warning("CRMain.handle_disc_req: "  + l_sep +\
                " got a response that wasn't in the correct format :" +\
                str(msg.attributes[utils.request_response]))
        else:

            #set boolean to show user we're requesting now
            ui_panels.cr_requesting = msg.attributes[utils.requesting]

            data = msg.attributes[utils.request_response].get(utils.data)
            error = msg.attributes[utils.request_response].get(utils.error)
            errors = msg.attributes[utils.request_response].get(utils.errors)
            logged_in = msg.attributes.get(utils.logged_in, None)
            
            if not logged_in is None:
                cr.logged_in = logged_in

            if errors is not None:
                for err in errors:
                    error_message = err.get('message')
                    # add this error message to the list of msgs for cloud
                    bpy.ops.crowdrender.add_cloud_issue("INVOKE_DEFAULT", 
                                err_text = error_message)
                    # 
                    # bpy.ops.crowdrender.show_discovery_error('INVOKE_DEFAULT', 
#                         err_text=error_message)    

            if error is not None:
                
                

                if error == utils.auth_required:
                    cr.logged_in = False
                    cr.cloud_credit = ""

                    ##RETURN EARLY
                    #need to return early here and not request again until the
                    # user logs in.

                    return

            if data is not None:
                
                rental_req_resp = data.get(utils.requestRentalInstances)
                user = data.get(utils.user)
                update_num_insts_req = data.get(utils.updateRentalInstanceCount)
                

                if user is not None:


                    refresh_interval = data.get(utils.refreshInterval, 30.0)

                    num_cloud_insts_discovery =\
                         user.get(utils.numberOfBlenderGridNodes, "?")

                    machines = user.get(utils.machines, None)

                    render_credit = user.get(utils.renderCredit, '')

                    

                    cr.cloud_credit = "{0:.2f}".format(render_credit)
                    cr.num_cloud_insts_discovery = str(num_cloud_insts_discovery)

                    node_list = machines





                elif rental_req_resp is not None:

                    update_rental_instance_count =\
                         data.get(utils.updateRentalInstanceCount)

                    if update_rental_instance_count is not None:
                        num_cloud_insts_discovery = \
                        update_rental_instance_count.get(utils.count)
                    else:
                        num_cloud_insts_discovery = rental_req_resp.get(
                                            utils.numberOfBlenderGridNodes, "?")

                    refresh_interval = rental_req_resp.get(utils.refreshInterval, 30.0)

                    machines = rental_req_resp.get(utils.machines, None)

                    render_credit = rental_req_resp.get(utils.renderCredit)

                    cr.cloud_credit = "{0:.2f}".format(render_credit)
                    cr.num_cloud_insts_discovery =\
                        str(num_cloud_insts_discovery)

                    node_list = machines

                    
                if update_num_insts_req is not None:

                    cr.num_cloud_insts_discovery =\
                        str(update_num_insts_req.get(utils.count))
                    
            _uuid = utils._uuid
            active = utils.active
            accessKey = utils.accessKey
            ip = utils.ip
            computerName = utils.computerName
            local = utils.local
            removed_nodes = {}
            if node_list is not None:
                disc_nodes_by_uuid = [node[_uuid] for node in node_list]              


            if not node_list:
                pass #TODO: think about making this logging info more useful
                    # it currently isn't and was blocking the UI for several seconds
                    # on a bad network for no real benefit to the user.
                # self.logger.warning("CRMain.handle_disc_req: "  + l_sep +\
#                     " attempted to extract data from response to discovery "+\
#                     "refresh"+\
#                     ", it failed: " + str(data))
            else:
                        

                for S in bpy.data.scenes:
                
                    
                    #create local variables to avoid slow re-evaluations in loops,
                    #see https://wiki.python.org/moin/PythonSpeed/PerformanceTips#Loops


                    cr_nodes_uuid = {node.node_uuid:node for node in S.cr_nodes}
                    

                    #create dotless functions for cr_nodes
                    find = S.cr_nodes.find
                    remove = S.cr_nodes.remove
                    cr_nodes_uuid_get = cr_nodes_uuid.get
                    cr_nodes_add = S.cr_nodes.add

                    ##REMOVE DEAD CLOUD NODES
                    #Create a list of the indices of nodes that are no longer
                    # active and need to be removed from the list
                    dead_nodes = [find(node.name) for node in S.cr_nodes\
                        if not node.node_uuid in disc_nodes_by_uuid and\
                            not node.node_local]

                    for dead_node in dead_nodes:
                        remove(dead_node)

                    ##UPDATE NODE LIST
                    for node in node_list:

                        node_uuid = node[_uuid]

                        # we don't want to display this computer in its
                        # own list, that would be silly, connecting to
                        # is only worth it if you're a crowdrender dev ;P
                        if node_uuid == self.machine_uuid: continue

                        cr_node = cr_nodes_uuid_get(node_uuid, None)


                        if not cr_node is None:
                            #we've found the node, so just update it, so long as its 
                            # version is a match
                            
                            m_data = node.get('machineData')
                            if m_data is not None:
                                version = m_data.get('crVersion')
                            else:
                                version = ''
                                
                            cr_node.cr_version = version

                            cr_node.node_active = node[active]

                            cr_node.node_access_key = node[accessKey]

                            cr_node.name = node[computerName]

                            if not node[local]:
                            
                                cr_node.node_address = node[ip]

                        else:
                            #there appears to be no node with the uuid we got, but check
                            # for the name, if there is one, just remove it
                            
                            m_data = node.get('machineData')
                            if  m_data is not None:                           
                                version = m_data.get('crVersion')
                            else:
                                version = ''
                            #the node doesn't yet exist, its probably new, so add it
                            new_node = cr_nodes_add()
                            new_node.cr_version = version
                            new_node.name = node[computerName]
                            new_node.node_active = node[active]
                            new_node.node_access_key = node[accessKey]
                            new_node.node_uuid = node_uuid
                            #The ip that is stored in discovery will be the WAN address
                            # which can't be used locally
                            if not node[local]:
                                new_node.node_local = False
                                new_node.node_address = node[ip]


        #tell the user we've removed incompatible nodes
        
        
        self.add_async_task(
            (self.null_op, [], {}),
            (self.refresh_discovery,
            [refresh_interval/1000], {}), #/1000 cause its given in milliseconds
            timeout=refresh_interval/1000 * 1.1)

        self.tag_redraw(C)


    def handle_new_node(self, C, msg):
        """ Handle msg that a new node is ready for connecting

        When a new node starts it signals the client with an ssp_alive messsage.
        This handler gets called to show the node's new status in the render nodes panel
        or, in the case of the local node, add it to the panel.

        """
        machine_uuid = msg.attributes[utils.machine_uuid]
        node_name = msg.attributes[utils.node_name]
        node_status = msg.attributes[utils.status_update]
        compute_devices = msg.attributes[utils.compute_devices]
        cr_version = msg.attributes[utils.crVersion]
             
        #create a temp file to store the node's feedback data in
        report_file = self.create_report_file(machine_uuid)
        
        
        for S in bpy.data.scenes:
            
            cr_nodes_uuid = {node.node_uuid:node for node in S.cr_nodes}
            cr_nodes_uuid.update({'local':S.crowd_render.local_node})
            
            #get the node by uuid if possible, otherwise look for the host name
            node = cr_nodes_uuid.get(machine_uuid, S.cr_nodes.get(node_name))
            
            if node is not None:
                #refresh a node's compute devices, remove the any that are saved
                # as they're considered stale.
                node.compute_devices.clear()
                node.node_state = node_status
                node.node_active = True
                node.node_uuid = machine_uuid
                node.cr_version = cr_version
                #node.compute_devices = compute_devices
                for item in compute_devices:
                    comp_device = node.compute_devices.add()
                    comp_device.name = item['type'] + " - " + item['name']
                    comp_device.type = item['type']
                    comp_device.id = item['id']
                    comp_device.use = item['use']
                
                
                node.node_report_path = report_file
                
                self.report({'INFO'}, node_name + " ready")
                self.logger.debug("CRMain.handle_new_node: "  + l_sep +\
                    " New node: " + node_name + \
                    " reported :" + states_user_sees[node_status])
                
            else:
                    
                # update the local node, its stored differently to remote nodes
                if machine_uuid == "local":
                    
                    new_n = S.crowd_render.local_node
                    new_n.node_uuid = "local"
                    new_n.node_report_path = report_file
                    
                    
                else:
                    # on loading/reloading a blend file, nodes
                    # are removed from the list that are not saved
                    # in that blend file, so connected nodes will appear
                    # as new nodes, so we handle them here.
                    new_n = S.cr_nodes.add()
                    new_n.name = node_name
                    new_n.node_uuid = machine_uuid
                    new_n.active = True
                    new_n.cr_version = cr_version
                    new_n.node_report_path = report_file
                    
                for item in compute_devices:
                    #don't add the same device more than once
                    comp_device = new_n.compute_devices.add()
                    comp_device.name = item['type'] + " - " + item['name']
                    comp_device.type = item['type']
                    comp_device.id = item['id']
                    comp_device.use = item['use']
                    
                self.report({'INFO'}, node_name + " ready")
                self.logger.debug("CRMain.handle_new_node: "  + l_sep +\
                    " New node: " + node_name + \
                    " reported :" + states_user_sees[node_status])
                        
                        
        self.tag_redraw(C)
        


    def connect_node_failed(self, C, msg):
        """ Update the visual status of a node to show a connect failed

        Arguments:
            C:      bpy.context -   reference to the current context in blender
            msg:    MsgWrapper  -   crowdrender.src.cr.utils.MsgWraper obj, must have
                attributes = {
                    utils.node_name:        string  -   unique name of the node
                    utils.node_address:     string  -   endpoint that was tried

        Returns:
            nothing

        Side Effects:
            updates the status of the node matching "node_name" in the msg argument
            to a connect failure so that the user can take remedial action

        Exceptions:
            None

        Description:


        """

        node_name = msg.attributes.get(utils.node_name, None)
        failed_addr = msg.attributes.get(utils.node_address, None)
        
        for S in bpy.data.scenes:  
          
            node = S.cr_nodes.get(node_name, None)

            if node is not None:
                node.node_state = utils.connect_failed
                self.report({'WARNING'},"Couldn't connect to " + str(node_name))
                self.logger.warning("CRMain.connect_node_failed" + l_sep +\
                    "couldn't connect to :" + str(node_name) + " at endpoint " +\
                        str(failed_addr))
            else:
                self.logger.error("CRMain.connect_node_failed" + l_sep +\
                    "Could not find this node to update its status: " +\
                    str(node_name))

        self.tag_redraw(C)


    def progress_update(self, C, msg):
        """ Update the upload progress for a node

        Arguments:
            C:      bpy.context -   reference to active context in blender
            msg:    MsgWrapper  -   crowdrender message wrapper object, must have:
                attributes = {
                        utils.node_uuid:string      - unique id for the node
                        utils.percent_complete:int  - obvious!
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

        node_uuid = msg.attributes[utils.node_uuid]
        node_name = msg.attributes[utils.node_name]
        node_state = msg.attributes.get(utils.status)
        
            #nodes should always be indexed by their uuid. Uuid's are unique
            # and therefore avoid glitches
        
        
        for s in bpy.data.scenes:
        
            cr_nodes_uuid = {node.node_uuid:node for node in s.cr_nodes}
            
            node = cr_nodes_uuid.get(node_uuid)
            
            if not node is None:
            
                if node_state is not None: node.node_state = node_state
                
                percent_complete = msg.attributes[utils.percent_complete]
                
                node.node_sync_progress = percent_complete
                
            else:
                self.report({'WARNING'},"Rcvd prog update for non-existent render node")
                self.logger.warning("CRMain.progress_update :" + l_sep +\
                    " Recevied progress update for non existent node: " + str(node_name)
                )
                
        self.tag_redraw(C)

    def status_update(self, C, msg):
        """ Update the status of a node so its visible to the user

        Arguments:
            C:      bpy.context -   reference to active context in blender
            msg:    MsgWrapper  -   crowdrender message wrapper object, must have:
                attributes = {
                        utils.node_uuid:string      - unique id for the node
                        utils.status_update:string  - status code, see utils.py
                            }

        Returns:
            None

        Side Effects:
            Sets status of the node identified by the uuid sent in the msg argument

        Exceptions:
            None

        Description:

            Updates the visible status label of a render node in the crowdrender panel.
            This method uses a custom dictionary that stores each render node by
            its uuid rather than its name (as is done in the bpy_prop_collection. This
            ensures that the nodes are always addressed by a unique id since bpy_prop_
            collection types allow entries with the same name.

        """
        
        
        if utils.node_uuid in msg.attributes:
            
            node_uuid = msg.attributes[utils.node_uuid]
            #nodes should always be indexed by their uuid. Uuid's are unique
            # and therefore avoid glitches
            for S in bpy.data.scenes:
                
                cr_nodes_uuid = {node.node_uuid:node for node in S.cr_nodes}
                cr_nodes_uuid.update({"local":S.crowd_render.local_node})
                
                node = cr_nodes_uuid.get(node_uuid)
                
                if node is None:
                #better add this node if its somehow not in the list
                    new_node = S.cr_nodes.add()
                    new_node.node_uuid = node_uuid
                    new_node.node_state = msg.attributes[utils.status_update]
                    new_node.node_active = msg.attributes[utils.active]
                    compute_devices = msg.attributes[utils.compute_devices]
                    new_node.node_A_auto = msg.attributes[utils.node_A_auto]
                    new_node.name = msg.attributes[utils.node_name]
                    
                    report_file = self.create_report_file(node_uuid)
                    
                    new_node.node_report_path = report_file
                    
                    write_report_data_file(report_file, 
                            report_data = ["Info: node status updated: " \
                                + states_user_sees[new_node.node_state]]
                                )
                    for item in compute_devices:
                    #don't add the same device more than once
                        comp_device = new_node.compute_devices.add()
                        comp_device.name = item['type'] + " - " + item['name']
                        comp_device.type = item['type']
                        comp_device.id = item['id']
                        
                    self.report({'INFO'}, new_node.name + " is " +\
                         states_user_sees[new_node.node_state])
                    
                elif msg.attributes[utils.status_update] == utils.exited:
                    
                    node.node_state = msg.attributes[utils.status_update]
                    #node.node_active = False
                    self.tag_redraw(C)
                    self.report({'INFO'}, node.name + " is " +\
                         states_user_sees[node.node_state])
                    
                else:
                    
                    node.node_active = msg.attributes[utils.active]
                    node.node_state = msg.attributes[utils.status_update]
                    compute_devices = msg.attributes[utils.compute_devices]
                    node.node_A_auto = msg.attributes[utils.node_A_auto]
                    write_report_data_file(node.node_report_path, 
                            report_data = ["Info: node status updated: " \
                                + states_user_sees[node.node_state]]
                                )
                    self.report({'INFO'}, node.name + " is " +\
                         states_user_sees[node.node_state])
                    
            self.tag_redraw(C)
                
    def repair_item(self, C, msg):
        """ Handle an update on the repair of a nodes hash tree
        
        Arguments:
            MsgWrapper -    Crowdrender MsgWrapper object, Must contain:
                command = utils.get_nodes_by_uuid
                s_uuid
                attributes = {utils.machine_uuid:   render node's uuid,
                            utils.status:           status of node,
                            utils.repair_item:      node name being repaired
                            }
        Returns:
            nothing
            
        Side Effects: 
            Causes the displayed status of the node to show the data block on the render
            node that is currently being repaired. Also sets the status to 5, 'repairing'
            
        Exceptions Raised:
            none
            
        Description:
            This method is part of the feedback mechanism for telling the user that one
            or more of their render nodes are in a repairing state and are trying to 
            reconcile the differences in their hash trees.
            
        """
        
        node_uuid = msg.attributes.get(utils.node_uuid)
        #nodes should always be indexed by their uuid. Uuid's are unique
        # and therefore avoid glitches
        cr_nodes_uuid = {node.node_uuid:node for node in C.scene.cr_nodes}
        cr_nodes_uuid.update({"local":C.scene.crowd_render.local_node})

        node = cr_nodes_uuid.get(node_uuid)
        
        if node is not None:
            
            node.node_state = msg.attributes.get(utils.status, utils.ready)
            node.node_repair_item = msg.attributes.get(utils.repair_item, "")
            
            write_report_data_file(node.node_report_path,
                   report_data =  ["Warning: " +\
                        msg.attributes.get(utils.repair_item, "") + " " +\
                         msg.attributes.get(utils.repair_message, "") + " " +\
                         msg.attributes.get(utils.repair_attr, "") +\
                         msg.attributes.get(utils.missing_block, "")]
                    )
            
            
        

    def send_nodes(self, C, msg):
        """ Handle a request from a server for the clients hash_tree nodes hash values

        Arguments:
            MsgWrapper -    Crowdrender MsgWrapper object, Must contain:
                command = utils.get_nodes_by_uuid
                s_uuid
                attributes = {utils.machine_uuid: Requesting machines uuid
                            }

        Returns:
            nothing

        Side Effects:
                Sends a MsgWrapper object to the SSP containing a dictionary, nodes.
                This dictionary contains hash_value and data_hash_value for each node
            in the hash_tree.

        Exceptions:
            None

        Description:
                This method responds to a request from the server_session. It receives
            a MsgWrapper object as an argument containing the id of the requesting server.
            It builds a dictionary containing hash data for each node in the hash_tree and
            creates a new MsgWrapper object to send back to the server containing this
            dictionary.

        """
        nodes = {}
        machine_uuid = msg.attributes[utils.machine_uuid]

        for node in self._hash_tree.nodes_by_uuid.values():
            nodes[node.uuid] = (node.hash_value, node.data_hash_value)

        # notify which node requested this
        rqst_node = [rqst_nd for rqst_nd in bpy.context.scene.cr_nodes\
                        if rqst_nd.node_uuid == machine_uuid]

        nodes_msg = utils.MsgWrapper(message = utils.get_nodes_by_uuid,
            attributes = {utils.nodes_by_uuid:nodes,
                            utils.machine_uuid:machine_uuid})

        nodes_msg.attributes[utils.message_uuid] = str(uuid.uuid4())

        request_queue.append(nodes_msg)

        self.logger.debug("CRClient.send_nodes: " + l_sep +\
            " Sending node hash values to " + rqst_node[0].name)



    def send_node_hashes(self, C, msg):

        nodes = msg.attributes[utils.node_uuid]
        machine_uuid = msg.attributes[utils.machine_uuid]
        
        nodes_data = {}

        for node_uuid in nodes:
        
            attrib_hashes = {}
            attributes = {}
        
            assert node_uuid in self._hash_tree.nodes_by_uuid

            node = self._hash_tree.nodes_by_uuid[node_uuid]
            
            nodes_data[node_uuid] = {utils.attributes:node.attributes,                 
                                    utils.attribute_hashes:node.attrib_hashes}

        node_msg = utils.MsgWrapper(message = utils.get_node_attrib_hashes,
                            s_uuid = msg.s_uuid,
                            attributes = {  
                                            utils.node_uuid:nodes_data,
                                            utils.machine_uuid:machine_uuid,
                                            utils.top_hash:self._hash_tree.top_hash})

        node_msg.attributes[utils.message_uuid] = str(uuid.uuid4())

        self.logger.debug("CRClient.send_nodes: " + l_sep +\
            "Sending hash and attribute data "
            )

        request_queue.append(node_msg)
        
class CR_OT_initialise_cip(bpy.types.Operator):
    """ Sends an init msg to the CIP
    
    """
    
    bl_idname = 'crowdrender.initialise_cip'
    bl_label = 'Initialise the Crowdrender system'
    bl_description = "initialises the master's Client Interface Process "
    
    top_hash: bpy.props.StringProperty(
            name= "top hash", 
            description= "hash value for the current session",
            default= '0')
    
    resync: bpy.props.BoolProperty(
                name= "resync", 
                description= "boolean - true if we're resyncing the current session",
                default= True)
        
    load_trusted: bpy.props.BoolProperty(
            name= "load trusted", 
            description= "boolean - true if we're allowing scripts to run",
            default= True)
    
    def file_saved_handler(self, *args):
        """ Handles event of the file being saved
        """
        self.file_saved= True
        
        
    
    @classmethod
    def poll(cls, context):
        return True
    
    def invoke(self, context, event):
        
        wm = context.window_manager
        wm.modal_handler_add(self)
        self.timer = wm.event_timer_add(0.032, window =context.window)
        bpy.app.handlers.save_post.append(self.file_saved_handler)
        
        self.file_saved = False
        
        blend_file_name = os.path.basename(bpy.data.filepath)
        if not blend_file_name: blend_file_name = 'untitled.blend'
        self.upload_task_new = UploadTask()
        temp_blend_file = os.path.join(
            self.upload_task_new.temp_folder.name, blend_file_name)
        self.upload_task_new.add_files([temp_blend_file])
        #create new upload task to track use of the temp copy of the blend file
        
        upload_tasks[self.upload_task_new.upload_task_id]= self.upload_task_new
        
        try:
            bpy.ops.wm.save_as_mainfile(
                filepath = temp_blend_file, 
                copy=True, 
                relative_remap=False,
                compress=False)
                
            
        except:
            location = "send_connect_msg.invoke"
            log_string = "Error caught when saving blend file"
            handle_generic_except(location, log_string)
            #bpy.app.handlers.save_post.remove(self.file_saved_handler)
            #wm.event_timer_remove(self.timer)
            
            exc_info = sys.exc_info()
            self.report({"WARNING"}, str(exc_info[1]))
            
        
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        
        if self.file_saved:
            return self.execute(context)
        return {'PASS_THROUGH'}
        
    def execute(self, context):
        """ Send the init message to the client interface to fully prepare it
        
        Arguments:
            context - bpy.context - blender's ui context 
                                     
        Returns
            Nothing
        
        Side Effects:
            Sends a message to the client interface process
        
        Exceptions:
            None
        
        Description:
            This method is part of the initialisation for a file being loaded. The
            method's goal is to send a msg to the client interface process telling it
            to initialise its self with the meta data of the file now loaded in the
            base application. 
            It will only do this, however, if there is a valid filepath, otherwise
            it will not initialise the client inteface process. It will log an info
            level msg stating that it was called but did not act because the file 
            path was not set. 
            
        """
        
        C = context
        wm = C.window_manager
        wm.event_timer_remove(self.timer)
        bpy.app.handlers.save_post.remove(self.file_saved_handler)
        # if there is no blend file yet, save a copy in the temp directory so that
        # we can still use this session with crowdrender. The user can save it later
        # and we shall update the user file path then
        
        session_uuid = rules.get_session_uuid(bpy.data)
        
        screen_res_x = C.scene.render.resolution_x * \
             C.scene.render.resolution_percentage / 100
        screen_res_y = C.scene.render.resolution_y *\
             C.scene.render.resolution_percentage / 100
             
        init_msg = utils.MsgWrapper(
            command = utils.init_session,
            attributes = {
                utils.session_uuid:session_uuid,
                utils.top_hash:int(self.top_hash),
                utils.session_path:wm.cr.session_path,
                utils.screen_size:(screen_res_x, screen_res_y),
                utils.resolution_x:C.scene.render.resolution_x,
                utils.resolution_y:C.scene.render.resolution_y,
                utils.resync:self.resync,
                utils.resolution_percent:C.scene.render.resolution_percentage,
                utils.load_trusted:self.load_trusted,
                utils.upload_task:[
                    self.upload_task_new.upload_task_id, 
                    self.upload_task_new.files]
                 })
        
        request_queue.append(init_msg)
        
        
        return {'FINISHED'}

class CR_OT_add_cloud_issue(bpy.types.Operator):
    """ Adds a cloud issue to the cloud issues list 
    """    
    
    bl_idname = "crowdrender.add_cloud_issue"
    bl_label = "add a cloud issue to the cloud issues list"
    
    err_text: bpy.props.StringProperty(name = "error message text", 
                    description= "error text of the error",
                    default="unexpected error")
    
    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):


        return {'FINISHED'}
      
    def invoke(self, context, event):
        
        #thanks to blender's odd handling of float numbers, we're using nano seconds
        # since the epoch to get a time as an integer for time stamping each issue
        new_issue = context.window_manager.cr.cloud_system_issues.add()
        new_issue.time_logged = int(time.time())
        new_issue.time_stamp = time.asctime(time.localtime(new_issue.time_logged))
        new_issue.error_message = self.err_text
        
        return self.execute(context)
    
    
        
class CR_OT_clear_cloud_issues(bpy.types.Operator):
    """ Clears all cloud issues from the cloud issues list
    """
    
    bl_idname = "crowdrender.clear_cloud_issues"
    bl_label = "clears all cloud issues from the cloud issues list"
    
    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
    
        context.window_manager.cr.cloud_system_issues.clear()

        return {'FINISHED'}
        
    def invoke(self, context, event):

        return self.execute(context)
    

class CR_OT_show_cloud_issues(bpy.types.Operator):
    """ Shows all issues received from Discovery
    """
    
    bl_idname = "crowdrender.show_discovery_issues"
    bl_label = "issues reported with your account (newest first)"
    
    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
#         self.report({'INFO'}, self.message)      

#         print(self.message)
        return {'FINISHED'}
        
    def invoke(self, context, event):

        wm = context.window_manager

        return wm.invoke_props_dialog(self, width = 800)
        
    def draw(self, context):
    
        row = self.layout.row()
        
        row.template_list("CloudIssuesList", #id of type of list
                            "", #list_id
                            context.window_manager.cr, #dataptr
                            "cloud_system_issues", #propname of the list data
                            context.window_manager.cr, # dataptr, points to active index
                            "cr_issue_index", #propname of the active index
                            item_dyntip_propname = "time_stamp", #propname for tooltip
                            rows = 5, 
                            maxrows = 0,
                            columns = 3)
        
        row.operator("crowdrender.clear_cloud_issues", icon='TRASH', text="")
        
        
class CR_OT_save_node_data(bpy.types.Operator):
    
    bl_idname = "crowdrender.save_node_data"
    bl_label = "save node reports to disk"
    bl_description = "Saves the report data for this node to disk"
    
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filename: bpy.props.StringProperty(subtype="FILE_NAME")
    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    node_uuid: bpy.props.StringProperty(name = "node uuid")
    
    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        # setup default path and file name for reporting log files.
        self.directory = os.path.expanduser("~/Desktop")
        self.node = None
        
        #get node
        cr_nodes_by_uuid = {node.node_uuid:node for node in context.scene.cr_nodes }
        
        # what the f*&k??? dictionaries don't have the 'update' attribute in blender?
        cr_nodes_by_uuid["local"] = context.scene.crowd_render.local_node
        
        self.node = cr_nodes_by_uuid.get(self.node_uuid, None)
        
        if self.node is not None:
        
            self.filename = self.node.name + "_report_data" + ".txt"

            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}
            
        else: return {'CANCELLED'}
        
    def modal(self, context, event):
        
        return {'RUNNING_MODAL'}
        
    def execute(self, context):
    
        #save the file to the user specified location
        
        if os.path.exists(self.node.node_report_path):
            shutil.copy2(self.node.node_report_path, self.filepath)
        else:
            f = open(self.filepath, "wt")
            for report in self.node.reports:
                f.writeline(report.time_stamp + " : " + report.message)
                
            f.close()
        
        return {'FINISHED'}

class CR_OT_clear_node_report(bpy.types.Operator):
    """ Clears all cloud issues from the cloud issues list
    """
    
    bl_idname = "crowdrender.clear_node_report"
    bl_label = "clears all node reports from a nodes reports list"
    
    node_uuid: bpy.props.StringProperty(name = "node unique id") 
    
    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
    
    
        self.node.reports.clear()
        
        report_file = self.node.node_report_path
        
        open(report_file, 'w').close()

        return {'FINISHED'}
        
    def invoke(self, context, event):
    
        nodes_by_uuid = {node.node_uuid:node for node in context.scene.cr_nodes}
        
        #local node is not in the collection
        if self.node_uuid == 'local': self.node = context.scene.crowd_render.local_node
        
        else:
        
            self.node = nodes_by_uuid.get(self.node_uuid)

        return self.execute(context)
        
class CR_OT_show_node_reports(bpy.types.Operator):
    """ Shows useful logging info from remote nodes
    """
    bl_idname = "crowdrender.show_node_reports"
    bl_label = "Show info, warnings and errors from this node"
    node_uuid: bpy.props.StringProperty(name = "node unique id")
    
    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        return {'FINISHED'}

    def invoke(self, context, event):

        wm = context.window_manager
        
        nodes_by_uuid = {node.node_uuid:node for node in context.scene.cr_nodes}
        
        #local node is not in the collection
        if self.node_uuid == 'local': self.node = context.scene.crowd_render.local_node
        
        else:
        
            self.node = nodes_by_uuid.get(self.node_uuid)
        
        if self.node is not None:    
        
            self.node.reports.clear()
        
            report_path = self.node.node_report_path
        
            if os.path.exists(report_path):
                #read all the lines from the temp report data file
            
                try:
                    f = open(report_path, "rt")
                
                    for line in f: 
                        
                        report = json.loads(line)
                        
                        new_report = self.node.reports.add()
                        new_report.time_logged = report["time_logged"]
                        new_report.time_stamp = report["time_stamp"]
                        new_report.message = new_report.name = \
                                report["message"].rstrip("\n")
                        new_report.level = report["level"]
                    
                except: 
                
                    location = "CR_OT_show_node_reports.invoke"
                    log_string =" couldn't read from the node's report data file"
                
                    handle_generic_except(location=location, log_string = log_string,
                        logger = ui_ops_logger) 
                        
                f.close()

        return wm.invoke_props_dialog(self, width = 1200)

#     def check(self, context): #bl280 segfaults on MacOS when pressing RETURN key
#         return True   #so keep this method commented out for now.
    
    def draw(self, context):
    
        
        
        row = self.layout.row()
        
        if self.node is None:
            
            pass#no data to display, this will cause the UI list to error also
        
        else:
        
            row.template_list("NodeReportList", #id of type of list
                                "", #list_id
                                self.node, #dataptr
                                "reports", #propname of the list data
                                self.node, # dataptr, points to active index
                                "report_index", #propname of the active index
                                item_dyntip_propname = "time_stamp", #propname for tooltip
                                rows = 5, 
                                maxrows = 0,
                                columns = 3)
            column = row.column()
            column.operator(
                "crowdrender.clear_node_report", 
                icon='TRASH', 
                text="").node_uuid = self.node_uuid
                
            column.operator("crowdrender.save_node_data", 
                        icon='FILE_TICK',
                        text='').node_uuid = self.node_uuid
           
#         row = self.layout.split(0.80)

class show_discovery_error(bpy.types.Operator):
    """ Show a panel with the load balancer data
    
    Description:
        Displays the load balance data and allows you to edit the amount of screen area
        given to each computer when in manual mode.
         
    """
    bl_idname = "crowdrender.show_discovery_error"
    bl_desription = " Show an error from discovery to the user"
    bl_label = "display a discovery error"
    err_text: bpy.props.StringProperty(name = "error message text", 
                    description= "error text of the error",
                    default="unexpected error")
    @classmethod
    def poll(cls, context):
        return True
    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=800)
    def execute(self, context):
        return {'FINISHED'}
    def draw(self, context):
        box = self.layout
        box.label(text = self.err_text, icon = 'ERROR')


class cr_conn_try_again(bpy.types.Operator):

    bl_idname = "crowdrender.conn_try_again"
    bl_label = "connection failed, trying again"
    bl_description = "op used to show a popup telling the user we're trying again to connect"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        wm = context.window_manager
        wm.popup_menu(trying_again_connect, title = "Crowdrender - trying to connect",
                            icon = 'INFO')

        return self.execute(context)

    def execute(self, context):

        self.report({'INFO'}, "had to try again to connect to a render node")
        return {'FINISHED'}


class cr_conn_failed(bpy.types.Operator):

    bl_idname = "crowdrender.conn_failed"
    bl_label = "connection failed permanently"
    bl_description = "op used to show a popup telling the user of a failed connection"

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        wm = context.window_manager
        wm.popup_menu(connect_failed, title = "Crowdrender - trying to connect",
                            icon = 'INFO')

        return self.execute(context)

    def execute(self, context):

        self.report({'WARNING'}, "the attempt to connect ultimately failed, please check" +\
        " the node you wish to connect to is working and can be reached on the network")
        return {'FINISHED'}

class cr_open_help(bpy.types.Operator):
    """ Opens help documentation in a web browser
    """

    bl_idname = "crowdrender.open_help"
    bl_label = "Opens help documentation in a web browser"

    def invoke(self, context, event):

        return self.execute(context)

    def execute(self, context):
        doc_url = config.read_config_file(
            [config.documentation])[config.documentation]
        bpy.ops.wm.url_open(url=doc_url)

        return {'FINISHED'}
        
class CROWDRENDER_OT_save_your_work(bpy.types.Operator):
    """ Opens a dialog exhorting the user to save their work 
    
        Crowdrender stores a uuid for the blend file on a dummy object, this needs
        the blend file to be saved, but we don't want to automatically do this as 
        it could cause problems for users that are using 2.80 and 2.79b concurrently
        as saving a 2.79b file in 2.80 makes it unusable again in 2.79b.
        
    """
    
    bl_idname = 'crowdrender.save_your_work'
    bl_label = 'Crowdrender'
    
    def invoke(self, context, event):
    
        return context.window_manager.invoke_props_dialog(self, width = 600)
    
    def execute(self, context):
    
        return {'FINISHED'}
        
    def draw(self, context):
    
        box = self.layout
        box.label(text = "This file should be saved now", icon = 'ERROR')
        box.label(text = "This file needs to be saved again if you want to ")
        box.label(text = "use it with Crowdrender.")
    

class cr_dummy(bpy.types.Operator):
    """ Dummy operator for operations that can't be done right now

        Display a pop up telling the user this operation can't be done
        right now.
    """
    bl_idname = "crowdrender.dummy"
    bl_label = "dummy operator"

    my_type: StringProperty()
    message: StringProperty()

    coll: CollectionProperty(type=settings.CRNodes)

    def execute(self, context):
#         self.report({'INFO'}, self.message)

        for item in self.coll:
            cr_node = context.scene.cr_nodes.get(item.name, None)
            if not cr_node is None:
                cr_node.node_address = item.node_address

#         print(self.message)
        return {'FINISHED'}

    def invoke(self, context, event):

        wm = context.window_manager

        return wm.invoke_props_dialog(self, width = 800)

    def draw(self, context):
        self.layout.label(text = "That operation can't be done right now")
        row = self.layout.split(0.25)
        row.prop(self, "my_type")
        row.prop(self, "message")
        for item in self.coll:
            row = self.layout.split(factor = 0.5)
            row.prop(item, "name")
            row.prop(item, "node_address")
#         row = self.layout.split(0.80)

def update_manual_loadb(self, context):
    context.scene.crowd_render.manual_load_balancer = self.manual_loadb
#         row.label("")

class show_load_balancer(bpy.types.Operator):
    """ Show a panel with the load balancer data
    
    Description:
        Displays the load balance data and allows you to edit the amount of screen area
        given to each computer when in manual mode.
         
    """
    bl_idname = "crowdrender.show_load_balancer"
    bl_desription = " show a panel containing the load balancer data"
    bl_label = "Edit load balancing"
    active_node: bpy.props.StringProperty(name = "active render node", 
                    description= "Node that is currently being tuned")
    manual_loadb: bpy.props.BoolProperty(name = "Manual load balancing",
                        description = "boolean to control whether manual load balancing",
                        default = False,
                        update = update_manual_loadb)
    logger = ui_ops_logger
    @classmethod
    def poll(cls, context):
        return True
        
    def invoke(self, context, event):
        
        S = context.scene
    
        local_node = context.scene.crowd_render.local_node
        
        self.nodes = {node.name:node for node in context.scene.cr_nodes\
            if node.node_state in {utils.synced, 
                                   utils.ready, 
                                   utils.rendering, 
                                   utils.downloading_results} and\
            node.node_render_active}
        
        if local_node.node_render_active:
            self.nodes.update({"local":local_node})
            
        self.manual_loadb = context.scene.crowd_render.manual_load_balancer
        
        #calculate the difference we need to add to each nodes fractional 
        # area if that difference is not 0
        alpha = 1.0 - sum([node.node_A_manual for node in self.nodes.values()])
        
        if len(self.nodes) > 1 and \
            (alpha > 1 / ( S.render.resolution_x * S.render.resolution_y) or\
            alpha < -1 / ( S.render.resolution_x * S.render.resolution_y)):
            
            for node in self.nodes.values():
                node.node_A_manual += alpha / len(self.nodes)
            
        elif len(self.nodes) == 1:
            #only one node so give it all the screen
            for node in self.nodes.values(): 
                node.node_A_manual = 1.0
#     bl_label = "OK"
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=800)
        
    def execute(self, context):
    
        return {'FINISHED'}

    def draw(self, context):

        layout = self.layout
        box = self.layout
        box.prop(self, "manual_loadb")
        if self.manual_loadb:
            for node in self.nodes.values():
                row = box.split(factor = 0.45)
                cr_node = context.scene.cr_nodes.get(node.name)
                if cr_node is not None:
                    row.label(text=cr_node.name)
                    row.prop(cr_node, "node_A_manual")
                elif cr_node is None and node.node_uuid == "local":
                    row.label(text=node.name)
                    row.prop(context.scene.crowd_render.local_node, "node_A_manual")
                else:
                    self.logger.error("Show load balancer failed to find node: " +\
                                     node.name)
                    self.report({"ERROR"}, "Could not find node: " + node.name)
        else:
            for node in self.nodes.values():
                row = box.split(factor = 0.45)
                row.enabled = False
                cr_node = context.scene.cr_nodes.get(node.name)
                if cr_node is not None:
                    row.label(text=cr_node.name)
                    row.prop(cr_node, "node_A_auto")
                elif cr_node is None and node.node_uuid == "local":
                    row.label(text=node.name)
                    row.prop(
                        context.scene.crowd_render.local_node, 
                        "node_A_auto")
                else:
                    self.logger.error(
                        "Show load balancer failed to find node: " +\
                                     node.name)
                    self.report({"ERROR"}, "Could not find node: " + node.name)
                    
    def check(self, context):
        scene = context.scene
        #first determine if we're in manual mode
        if self.manual_loadb:
            # we need to calculate the value of each node's screen area as a fraction
            # of the total area. The user will change one of their node's values
            # and we need to adjust the rest so all the fractions sum to 1.0
            
            #first, which one did the user change?
            active_node = self.nodes.get(
                scene.crowd_render.active_load_balance_node)
            
            if active_node is not None:
                self.report({"INFO"}, "You changed " + active_node.name)
            
                # The active node's value does not change, but we must find the right
                # factor to scale the values of the other nodes by.
                gamma = (1.0 - active_node.node_A_manual) \
                    / sum ( [ node.node_A_manual for node in self.nodes.values()\
                     if not (node == active_node and len(self.nodes) > 1) ] )
            
                # apply the correction
                for node in self.nodes.values():
                    if not node == active_node: 
                        node.node_A_manual *= gamma
            else:
                self.report({"INFO"},"No node selected")
            
        else:
            pass# the values need to be derived from the data kept in the cip
        return True
        
class connect_remote_server(bpy.types.Operator):
    """ Connect to a remote server
    """

    bl_idname = "crowdrender.connect_remote_server"
    bl_label = "Connects to a remote crowdrender server"


    node_name: StringProperty(
        name="node name",
        description="Authorisation token required to access BG system",
        maxlen = 128,
        default = ""
        )
                
    logger = ui_ops_logger


    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        self.nodes = []

        if not self.node_name == "":

            import ipaddress

            #get ref to the node in question
            node = context.scene.cr_nodes.get(self.node_name, None)
            
            if node is not None: self.nodes = [node]


        else:

            self.nodes = context.scene.cr_nodes


        if len(self.nodes) == 0:
            #EXIT because there are no nodes to connect to
            self.report({'WARNING'}, 
                "No nodes in your list, please add a node first")
            
            ret = {'CANCELLED'}
        else:
            #TRY To connect
            from concurrent import futures



            self.connecting_nodes = {}
            self.needs_ip_address = {}

        
            #TODO: we need a more general concept than just whether a node
            # is local or not. I think we need the concept of "ownership". 
            # nodes can be remote (i.e. the local flag should be false)
            # but still be owned by the user and should persist in their
            # node list.

            # Here we attempt to resolve the ip addresses of the nodes, and, 
            # because the socket lib on different OS platforms requires 
            # ".local" for some names and not for others, we try both
            # using threads to ensure that the user doesn't have to remember
            # when to use .local. This avoids support requests for what should
            # be simples.
            

            node_names = [node.name for node in self.nodes]
            
            if not platform.system() == "Windows":
                node_names.extend([node.name + ".local" for node in self.nodes])

            with futures.ThreadPoolExecutor(
                        max_workers = 2 * len(self.nodes)) as executor:

                host_names_to_try = {
                    executor.submit(self.resolve_host, host_name):host_name\
                     for host_name in node_names
                                    }

                for future in futures.as_completed(host_names_to_try):
                    host_name = host_names_to_try[future]

                    try:
                        server_address = future.result(timeout = 1)

                        if not server_address == "":
                        
                            node_name = host_name.split(".")[0]
                            node = context.scene.cr_nodes.get(node_name)
                            
                            #legacy check for people still using node_name.local
                            if node is None: 
                                node = context.scene.cr_nodes.get(host_name)
                        
                            self.connecting_nodes[node_name] = node
                            node.node_address = server_address
                        

                    except Exception:
                    
                        location= "connect_remote_server.invoke"
                        log_string = "Unexpected error when trying "+\
                        " to resolve host name: " + host_name +\
                        " for node name: " + node_name
                    
                        handle_generic_except(location, log_string, self.logger)
        
        # final check for each node
            for node in self.nodes:
                        
                # Uh oh, screwed up, the host name resolution didn't work so we 
                # need to add this node to a list of nodes that will appear at the 
                # end of this op in a dialogue box asking the user to input the
                # ip addresses for each node that didn't resolve properly.
                if not node.name in self.connecting_nodes and\
                    not node.node_local:
                
                    self.connecting_nodes[node.name] = node
            
            # Next we check to see if the node has a saved address, we'll give this
            # a shot as a last resort. We should only do this if there was no way to 
            # resolve the node's address from its host name and its not a local node
                elif not node.name in self.connecting_nodes and\
                    not node.node_address=="":
            
                    self.connecting_nodes[node.name] = node
            
            # Finally if all else fails we can just ask the user for an ip address
            
                else:
            
                    self.needs_ip_address[node.name] = node

            wm = context.window_manager
            ret =  wm.invoke_props_dialog(self, width=800)

        return ret


    def draw(self, context):
        
        layout = self.layout
        
        
        box = layout.box()
        box.label(text = "Nodes requiring IP address")
        
        connecting_nodes = list(self.connecting_nodes.values())
        
        nodes = [node for node in self.nodes if not node in connecting_nodes]
        
        for node in nodes:
            
            row = box.split(factor = 0.45)
            row.prop(context.scene.cr_nodes[node.name], "name")
            row.prop(context.scene.cr_nodes[node.name], "node_address")
            
        box2 = layout.box()
        
        box2.label(text = "Nodes ready to connect")
        for node in connecting_nodes:
            row = box2.split(factor = 0.45)
            row.prop(context.scene.cr_nodes[node.name], "name")
            row.prop(context.scene.cr_nodes[node.name], "node_address")



    def resolve_host (self, host_name):

        import socket

        try:

            ip_address = socket.gethostbyname(host_name)

            result = ip_address

        except socket.gaierror:
            #in this case we'd need to pop up a dialogue to
            # get them to enter the address manually
            result =  ""

        return result

    def execute(self, context):
        #call to attempt a connection to the remote server
        import ipaddress
        context.area.tag_redraw()
        #bpy.app.handlers.scene_update_post.remove(self.ui_tag_updater.update)
        #
                #send connect request to CIP that we want to connect

        render_nodes = {}


        for node in self.needs_ip_address.values():
            try:
                res = ipaddress.ip_address(node.node_address)
                render_nodes[node.name] = node
            except ValueError:
                self.report({'WARNING'}, "Render Node: " + node.name +\
                     " had invalid address, skipping connect")

        self.connecting_nodes.update(render_nodes)

        if self.connecting_nodes:

            nodes = [{  
                'name':name,
                'cr_version': node.cr_version,
                'node_address':node.node_address,
                'node_state':node.node_state,
                'node_uuid':node.node_uuid,
                'node_access_key':node.node_access_key,
                'node_image_coords':node.node_image_coords,
                'node_local':node.node_local,
                'node_sync_progress':node.node_sync_progress,
                'node_render_progress':node.node_render_progress,
                'node_result_progress':node.node_result_progress,
                'node_repair_item':node.node_repair_item,
                'node_active':node.node_active,
                'node_render_active':node.node_render_active,
                'node_A_manual':node.node_A_manual,
                'node_A_auto':node.node_A_auto,
                'node_tile_x':node.node_tile_x,
                'node_tile_y':node.node_tile_y,
                'node_machine_cores':node.node_machine_cores,
                'node_report_path':node.node_report_path,
                'compute_devices':[
                    {'name':device.name,
                     'use':device.use,
                     'id':device.id,
                     'type':device.type} for device in node.compute_devices],
                'compute_device':node.compute_device,
                'process_threads':node.process_threads,
                'threads_mode':node.threads_mode,
                'reports':[
                    {'name':report.name,
                    'message':report.message,
                    'level':report.level,
                    'time_stamp':report.time_stamp,
                    'time_logged':report.time_logged
                    } for report in node.reports],
                'report_index':node.report_index
                    } for name, node in self.connecting_nodes.items()]
                            
            bpy.ops.crowdrender.send_connect_msg(
                'INVOKE_DEFAULT', cr_nodes = nodes)

            self.report({'INFO'}, "Connecting to nodes now")

        else:

            self.report({'WARNING'}, "No nodes had addresses to connect!")


        return {'FINISHED'}

    # def check(context):
#         return True
class send_connect_msg(bpy.types.Operator):
    """ Save blend file and then snd connect msg to CIP
    
    This operator class is part of the connection flow for connecting to 
    a render node. It is needed since we can't do the entire operation in 
    jst one operator. The reason for this is that we need to show the user
    a dialogue box in some cases, like where a node needs an ip. This means 
    that we can't use modal owing to the design of the operator base type.
    Essentially you cannot call an operator invoke, then show a dialogue, h
    then enter a modal operator, at least not as far as I know. 
    
    So this operator is called from the execute of the connect_server_node 
    operator. All it does is save the blend file and then send the required message.
    
     
    """
    bl_idname = "crowdrender.send_connect_msg"
    bl_label = "Send connect data to CIP"
    cr_nodes: bpy.props.CollectionProperty(type = settings.CRNodes)
    file_saved = False
    logger = ui_ops_logger
    
    def save_file_handler(self, *args):
        """ This handler is used to detect when the file is saved.
        Once the file has been saved this handler should be called. The handler
        is registered during the invole call for this operator. Once the file has
        been saved it will be called allowing the resync to begin.
        """
        self.file_saved=True
        
    @classmethod
    def poll(cls, context):
        return True
        
    def invoke(self, context, event):
    
        wm = context.window_manager
        wm.modal_handler_add(self)
        bpy.app.handlers.save_post.append(self.save_file_handler)
        
        #create temporary file path for copy of blend files, and a new upload
        #task
        blend_file_name = os.path.basename(bpy.data.filepath)
        if not blend_file_name: blend_file_name = 'untitled.blend'
        self.upload_task_new = UploadTask()
        temp_blend_file = os.path.join(
            self.upload_task_new.temp_folder.name, blend_file_name)
        self.upload_task_new.add_files([temp_blend_file])
        #create new upload task to track use of the temp copy of the blend file
        
        upload_tasks[self.upload_task_new.upload_task_id]= self.upload_task_new
        
        #try saving a copy of the blend file, for use in transferring to nodes
        try:
            
            bpy.ops.wm.save_as_mainfile(
                filepath = temp_blend_file, 
                copy=True, 
                relative_remap=False,
                compress=False)
            
        except:
            location = "send_connect_msg.invoke"
            log_string = "Error caught when saving blend file"
            handle_generic_except(location, log_string, self.logger)
            exc_info = sys.exc_info()
            self.report({"WARNING"}, str(exc_info[1]))
            
        self.timer = wm.event_timer_add(0.032, window =context.window)
        return {"RUNNING_MODAL"}
        
    def modal(self, context, event):
        if event.type == 'TIMER':
            if self.file_saved: 
                ret = self.execute(context)
            else: ret = {'PASS_THROUGH'}
        else: ret = {'PASS_THROUGH'}
        return ret
        
    def execute(self, context):
        bpy.app.handlers.save_post.remove(self.save_file_handler)
        wm = context.window_manager
        wm.event_timer_remove(self.timer)
        conn_msg = MsgWrapper(command = utils.connection_req,
            attributes = {
                utils.upload_task:[
                    self.upload_task_new.upload_task_id, 
                    self.upload_task_new.files],
                utils.render_nodes:
                    {node.name:{utils.node_address:node.node_address,
                    utils.node_access_key:node.node_access_key,
                    utils.node_uuid:node.node_uuid}\
             for node in self.cr_nodes}}
                        )
        request_queue.append(conn_msg)
        return {"FINISHED"}

class change_instance_number(bpy.types.Operator):
    """ Change the number of instances to request on discovery
    """

    bl_idname = "crowdrender.change_instance_number"
    bl_label = "Change the number of instances being requested"

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        self.report({'INFO'}, " changing number of instances requested to  " +\
            str(context.window_manager.cr.num_cloud_instances))

        return self.execute(context)

    def execute(self, context):
        request_uuid = uuid.uuid4().int

        num_instance_req_change_msg = MsgWrapper(command = utils.change_num_instances,
            attributes = {utils._uuid:request_uuid,
            utils.num_instances:context.window_manager.cr.num_cloud_instances}
                )

        request_queue.append(num_instance_req_change_msg)

        return {'FINISHED'}

class start_requesting_cloud_insts(bpy.types.Operator):
    """ Start requesting number of instances, warn if zero
    """

    bl_idname = "crowdrender.start_instance_request"
    bl_label = "Start cloud nodes"

    @classmethod
    def poll(cls, context):

        return True
#         else: return True

    def invoke(self, context, event):
    
        wm = context.window_manager

        if wm.cr.num_cloud_instances < 1:
        
            self.report({'ERROR'}, "Please request at least 1 node!!")
            
            return {'CANCELLED'}
            
        else:
        
            self.report({'INFO'}, "requesting " +\
             str(context.window_manager.cr.num_cloud_instances) +\
              " cloud instances")

            bpy.ops.crowdrender.notify_now_requesting('INVOKE_DEFAULT')

            return self.execute(context)

    def execute(self, context):

        request_uuid = uuid.uuid4().int
        #Prepare the response that will be a heartbeat
        start_msg = MsgWrapper( command = utils.start_rental_request,
            attributes = {utils.on_complete:utils.discovery_refresh_rental,
            utils._uuid:request_uuid,
            utils.crVersion:"_".join(map(str, crowdrender.cr_version)),
            utils.blVersion:"_".join(map(str, bpy.app.version)),
            utils.num_instances:context.window_manager.cr.num_cloud_instances})

        request_queue.append(start_msg)

        return {'FINISHED'}

class stop_requesting_cloud_instances(bpy.types.Operator):
    """ Stop requesting instances

    """
    bl_idname = "crowdrender.stop_instance_request"
    bl_label = "Stop Cloud nodes"




    @classmethod
    def poll(cls, context):

        return True
#         else: return True

    def invoke(self, context, event):
        """ stops the polled request of the cloud and requests 0 instances
        """
        self.report({'INFO'}, "Stopping cloud instances")

        return self.execute(context)



    def execute(self, context):
        """ Schedule a msg to be sent to discovery to stop requesting nodes
        """




        request_uuid = uuid.uuid4().int
        #Prepare the response that will be a heartbeat
        stop_msg = MsgWrapper( command = utils.stop_rental_request,
            attributes = {utils.on_complete:'', #blank string is a no-op
                                                # stops additional rqst loops starting
            utils._uuid:request_uuid,
            utils.crVersion:"_".join(map(str, crowdrender.cr_version)),
            utils.blVersion:"_".join(map(str, bpy.app.version)),
            utils.num_instances:0})

        request_queue.append(stop_msg)

        return {'FINISHED'}

class notify_requesting(bpy.types.Operator):
    """ Show a notification explaining the wait time for requesting an instance
    """

    bl_idname = "crowdrender.notify_now_requesting"
    bl_description = "Show notification when user requests cloud instances"
    bl_label = "Started to request Cloud Render Nodes"
    bl_options = {'INTERNAL'}

    show_req_notification: BoolProperty(
            name ="show this notification again",
            options = {'SKIP_SAVE'},
            description = "boolean property, True if the user has chosen to show this",
            default =True
            )

    def invoke(self, context, event):


        config_item = read_config_file([utils.show_req_notification])

        self.show_req_notification = config_item[utils.show_req_notification]

        if self.show_req_notification:
            wm = context.window_manager
            return wm.invoke_props_dialog(self, width=800)

        return {'FINISHED'}

    def execute(self, context):

        #write back the value of the notification pref so that its stored for next time
        write_config_file({utils.show_req_notification:self.show_req_notification})

        return {'FINISHED'}

    def draw(self, context):

        layout = self.layout
        layout.label(text="Great! We're working on that request, just to let you know it")
        layout.label(text=" can take up to five minutes before nodes are")
        layout.label(text=" be ready to connect. So please be patient and keep blender open.")
        layout.label(text=" You'll see the node starting up soon in your list of render nodes.")
        layout.prop(self, "show_req_notification")

class CR_OT_logout_cloud(bpy.types.Operator):
    """ Log this computer out of CR cloud
    """
    
    bl_idname = "crowdrender.crowdrender_logout"
    bl_label = "Logout"
    bl_description = " logout of the crowdrender distributed rendering system"


    @classmethod
    def poll(cls, context):
        return True


    def invoke(self, context, event):
        
        cr = context.window_manager.cr
        cr.user_name = ""
        cr.password = ""
        cr.logged_in = False
        cr.cloud_credit = ""
        
        logout_rqst_msg = utils.MsgWrapper(command = utils.logout)

        request_queue.append(logout_rqst_msg)
        
        
        return {'FINISHED'}

class login_cloud(bpy.types.Operator):
    """ Connect to a remote server
    """

    bl_idname = "crowdrender.crowdrender_login"
    bl_label = "Login"
    bl_description = " Login to the crowdrender distributed rendering system"






    @classmethod
    def poll(cls, context):
#         if cls.started and response is None:
        return True
#         else: return True



    def invoke(self, context, event):



        user_name = context.window_manager.cr.user_name
        password = context.window_manager.cr.password


        login_rqst_msg = utils.MsgWrapper(command = utils.discovery_login,
            attributes = {utils.user_name:user_name,
                        utils.password:password,
                        utils.on_complete:utils.discovery_login}
            )

        request_queue.append(login_rqst_msg)

        return {'FINISHED'}

class cancel_connect_remote_server(bpy.types.Operator):
    """Connect to a remote server
    """

    bl_idname = "crowdrender.cancel_connect_remote_server"
    bl_label = "Cancels connecting to a remote crowdrender server"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        #call to attempt a connection to the remote server

        #TODO: need a better method of accessing the client's messaging
        # system than this. This method assumes that the client's name
        # is available in the symbol table. When the package is imported however
        # this is not going to be the case.

        client = sys.modules[__package__].client.cr_client

        msg = utils.MsgWrapper( command = utils.cancel_connection,
                                attributes  = {'success':'not_successful'}
                                    )

        #Place this message in the queue to be sent.
        client.cancel_connect_remote_server(msg)

        context.area.tag_redraw()

        return{'FINISHED'}

    def invoke(self, context, event):

        return self.execute(context)

class CR_OT_render_still(bpy.types.Operator):
    bl_idname = 'crowdrender.render_still'
    bl_label = 'Crowdrender: Render Still'
    bl_description = ' Operator to allow Render Still keypress to call pre_render'
    cr_animation: bpy.props.BoolProperty(name="animation")
    
    def execute(self, context):
        
        context.scene.render.engine = crowdrender.package_name
        
        bpy.ops.render.render(
            'INVOKE_DEFAULT', 
            animation=self.cr_animation)
        
        
        return{'FINISHED'}

class CR_OT_render_anim(bpy.types.Operator):
    bl_idname = 'crowdrender.render_anim'
    bl_label = 'Crowdrender: Animation'
    bl_description = ' Operator to allow Animation keypress to call pre_render'
    cr_animation: bpy.props.BoolProperty(name="animation")
    
    def execute(self, context):
        
        
        context.scene.render.engine = crowdrender.package_name
        
        bpy.ops.render.render(
            'INVOKE_DEFAULT', 
            animation=self.cr_animation)
        
        return{'FINISHED'}



class NetworkErrorOperator(bpy.types.Operator):
    bl_idname = "crowdrender.network_error"
    bl_label = "Can't find a valid network"

    def execute(self, context):

        wm = context.window_manager

        wm.popup_menu(get_ip_failed_draw, title = 'OOps', icon = 'INFO')

        return {'FINISHED'}

class IncorrectEngineOperator(bpy.types.Operator):
    bl_idname = "crowdrender.incorrect_engine_notificaiton"
    bl_label = "Incorrect engine choice"

    def execute(self, context):
        
        wm = context.window_manager
        
        wm.popup_menu(incorrect_engine, title = "Oops!", icon = 'ERROR')
        
        return{'FINISHED'}

class ResyncRemoteMachine(bpy.types.Operator):
    
    bl_idname = "crowdrender.resync_remote_machine"
    bl_label = "attempt to resynchronise the data on a remote machine"
    bl_description = "resynchronise nodes (sends entire blend file again)"
    file_saved = False # don't send the file until its been saved!
    engine = ''
    node_name: StringProperty(
                name="node name",
                description="unique id for this node in crowdrender",
                maxlen = 128,
                default = ""
                )
    
    
    def save_file_handler(self, *args):
        """ This handler is used to detect when the file is saved.

        Once the file has been saved this handler should be called. The handler
        is registered during the invole call for this operator. Once the file has
        been saved it will be called allowing the resync to begin.

        """
        self.file_saved=True

    @classmethod
    def poll(cls, context):
        return True
    
    def invoke(self, context, event):
        
        
        print("RESYNCING: ", id(self))
        
        self.file_saved = False
        
        wm = context.window_manager
        wm.modal_handler_add(self)
        self.timer = wm.event_timer_add(0.0667, window = context.window)
        bpy.app.handlers.save_post.append(self.save_file_handler)
        
        #create an upload task to manage creating and destroying temp files
        # used for the file transfer
        self.upload_task_new = UploadTask()
        upload_tasks[self.upload_task_new.upload_task_id]= self.upload_task_new
        blend_file_name = os.path.basename(bpy.data.filepath)
        
        if not blend_file_name: blend_file_name = 'untitled.blend'
        temp_blend_file = os.path.join(
            self.upload_task_new.temp_folder.name, blend_file_name)
        self.upload_task_new.add_files([temp_blend_file])
        
        upload_tasks[self.upload_task_new.upload_task_id]= self.upload_task_new
        
        try:
            
            bpy.ops.wm.save_as_mainfile(
                filepath = temp_blend_file, 
                copy=True, 
                relative_remap=False,
                compress=False)
            
        except:
            
            exc_info = sys.exc_info()
            
            print("Error caught when saving blend file: ",
                                str(exc_info[0]),
                                " : ",
                                str(exc_info[1]))
            
            self.report({'WARNING'}, str(exc_info[1]))
            
            
        self.machines_resyncing = list()
        
        
        return {'RUNNING_MODAL'}
    
    def check(self, context):
        return True
    
    
    def modal(self, context, event):
        
        if event.type == 'TIMER':
            
            #we need to wait for blender to save its file before we start to transfer it.
            
            if self.file_saved:
                
                #stop repeated attempts to send the file save message!
                self.file_saved = False
                
                ret = self.execute(context)
                
            else:
                ret = {'PASS_THROUGH'}
                
            
            return ret
        
        return {'PASS_THROUGH'}
    
    
    def execute(self, context):
        
        wm = context.window_manager
        wm.event_timer_remove(self.timer)
        bpy.app.handlers.save_post.remove(self.save_file_handler)
        
        load_trusted = not bpy.app.autoexec_fail
        
        if not self.node_name == "":
            
            #get ref to the node in question
            node = context.scene.cr_nodes.get(self.node_name, None)
            
            nodes = {self.node_name:node}
            
        else:
            
            nodes = context.scene.cr_nodes
        
        
        resync_msg = MsgWrapper(
            command = utils.resync,
            attributes = {
                utils.render_nodes:
                    {node.node_uuid:node.node_address\
                        for node in nodes.values()},
                utils.load_trusted:load_trusted,
                utils.resync:True,
                utils.upload_task:[
                    self.upload_task_new.upload_task_id, 
                    self.upload_task_new.files]}
                 )
        
        request_queue.append(resync_msg)
        
        return {'FINISHED'}

class cr_discover_local_ip(bpy.types.Operator):
    bl_idname = "crowdrender.get_local_ip"
    bl_label = "get local IP address"

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        # start the process of acquiring the ip address

        import ipaddress

        #here we get the network device data, including device name and address

        self.local_ip_data = network_engine.discover_local_ip()

        self.valid_addresses = list()



        for ip_data in self.local_ip_data:

            try:
                #Try the first ip in the list, hmmm why don't we add all of them?
                ipaddress.ip_address(ip_data[0])

                self.valid_addresses.append(ip_data)



            except ValueError:

                pass

            except Exception:

                #oops!
                self.report({'ERROR'}, "failed trying to get valid addresses from the network")


        if not len(self.valid_addresses) > 0:



            client = sys.modules[__package__].client.cr_client

            client.status = utils.no_network

            wm = context.window_manager

            self.report({'WARNING'}, "uh oh - Failed to find a network connection, check" +\
                " your network connections!")

            # open dialogue box and alert user to the issue, they need to check their
            # network connections and try again.
            wm.popup_menu(get_ip_failed_draw, title = "Crowdrender - network issues",
                            icon = 'INFO')

            return {'FINISHED'}

        else:

            return self.execute(context)








    def execute(self, context):
        #finalise the IP address and populate the property that stores the
        # ip address
        wm = context.window_manager


        #have to get the right format for the enumeration property
        local_addresses = tuple(self.valid_addresses)

        # bpy.types.CrowdRenderSettings.local_address = EnumProperty(
#                 name="Local address",
#                 description="IP address of your computer",
#                 items = local_addresses,
#                 default = local_addresses[0][0],
#                 update = settings.client_addr_update_callback
#                                                                  )
#         settings.client_addr_update_callback(self, context)
#
#         client = sys.modules[__package__].client.cr_client
#
#
#         client.status = utils.ready

        wm.popup_menu(get_ip_success, title = "Crowdrender - Discovered network",
                            icon = 'INFO')



        return {'FINISHED'}

class RemCRNode(bpy.types.Operator):
    """ Removes the active node"""
    bl_idname = "crowdrender.rem_cr_node"
    bl_label = "remove a node"


    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        user_preferences = context.preferences
        addon_prefs = user_preferences.addons[crowdrender.package_name].preferences

        use_debug = addon_prefs.use_debug

        if use_debug and 'remote_debugger' in user_preferences.addons:
            bpy.ops.debug.connect_debugger_pydev()

        self.requested_to_disconnect = {}

        cr_nodes = context.scene.cr_nodes

        node_ind_to_disc = context.scene.cr_node_index




        try:
        # get the uuid of the underlying machine interface and prepare
        # to disconnect it.
            node_to_disc = cr_nodes[node_ind_to_disc]
            node_name = node_to_disc.name
            node_uuid = node_to_disc.node_uuid



            disconnect_msg = utils.MsgWrapper(

                        command = utils.disconnect,
                        attributes = {
                               utils.machine_uuid:node_uuid
                                    }
                        )

            request_queue.append(disconnect_msg)

            for S in bpy.data.scenes:
            
                
                remove_node = S.cr_nodes.find(node_name)
                
                if remove_node > -1 : S.cr_nodes.remove(remove_node)
            



        except IndexError:

            #remove the node from the ui immediately and execute since
            # there will be no machine to disconnect.

            #cr_nodes.remove(node_ind_to_disc)
            if len(cr_nodes) < 1:

                self.report({'INFO'},"No nodes to remove!")

            else:

                self.report({"WARNING"}, "Node not found!")
                
        

        return self.execute(context)



    def execute(self, context):

#         wm = context.window_manager
#
#         wm.event_timer_remove(self.timer)

        return {'FINISHED'}

class AddCRNode(bpy.types.Operator):
    """Adds a new node"""
    bl_idname = "crowdrender.add_cr_node"
    bl_label = "Add a node"
    MAX_MACHINES = 1000

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        scene = context.scene
        wm = context.window_manager

        if len(scene.cr_nodes) >= self.MAX_MACHINES:
            #wm.invoke_popup(sorry!)
            return{'CANCELLED'}

        name = get_unique_name("new node", context)




        new_node = context.scene.cr_nodes.add()
        new_node.name = name

        #new_node.uuid = str(uuid.uuid4())

        #new_node.name = new_node.node_host_name
        #new_node.node_host_name = "new host"
        #new_node.node_address = "default"
        return {'FINISHED'}
        


class NodeSettingsDialog(bpy.types.Operator):
    """Access settings for this node"""
    bl_idname = "crowdrender.node_settings_dialog"
    bl_label = ""
    node_name: bpy.props.StringProperty(name="node_name")

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def check(self, context):
        return True

    def draw(self, context):
        if self.node_name == "local":
            cr_nodes_settings = context.scene.crowd_render.local_node
        else:
            cr_nodes_settings = context.scene.cr_nodes[self.node_name]
        layout = self.layout

        layout.label(text = self.node_name)

        first_row = layout.row(align=True)


        first_row = layout.row()

        if self.node_name == "local":
            pass
        else:
            first_row.label(text = "Resync")
            first_row.operator("crowdrender.resync_remote_machine",
                    icon='FILE_REFRESH', text = "", 
                        emboss=False).node_name=self.node_name

        sec_row = layout.row()

        sec_row.label(text = "tile_x")
        sec_row.prop(cr_nodes_settings, "node_tile_x", text="")

        thrd_row = layout.row(align=True)
        
        thrd_row.label(text = "tile_y")
        thrd_row.prop(cr_nodes_settings, "node_tile_y", text="")
        
        row = layout.row(align=True)
        row.label(text = "Select compute device(s)")
        row = layout.row(align=True)
        row.prop(cr_nodes_settings, 'compute_device', text='')
        
        for device in cr_nodes_settings.compute_devices:
            if device.type == cr_nodes_settings.compute_device:
                row = layout.row(align=False)
                row.prop(device, 'use', text='')
                row.label(text = device.name)
        row = layout.row(align=True)
        row.label(text = 'Threads Mode')
        row.prop(cr_nodes_settings, 'threads_mode', text='')
        row = layout.row(align=True)
        row.label(text = 'Threads')
        if cr_nodes_settings.threads_mode == 'Auto-detect':
            row.enabled = False                          
        else:
            row.enabled = True                        
        row.prop(cr_nodes_settings, "process_threads", text='')


class ConnectNode(bpy.types.Operator):

    bl_idname = "crowdrender.connect_node"
    bl_label = "connect to node"
    bl_description = "Connect to selected node"

    manual_address: bpy.props.StringProperty(name = "ip address", default="")

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):


        #if there are no nodes yet, don't attempt to cancel as this will
        # raise an index error

        scene = context.scene

        if len(scene.cr_nodes) < 1:

           return {'CANCELLED'}

        act_node_ind = scene.cr_node_index
        act_node = scene.cr_nodes[act_node_ind]
        node_hostname = act_node.name

        if not (act_node.node_state == utils.null or\
            act_node.node_state == utils.connect_failed):

            return {'CANCELLED'}

        import socket

        try:

#             if sys.platform == 'darwin': node_hostname += ".local"

            ip_address = socket.gethostbyname(node_hostname)
            self.manual_address = ip_address

            return self.execute(context)

        except socket.gaierror:
            #in this case we'd need to pop up a dialogue to
            # get them to enter the address manually
            result =  context.window_manager.invoke_props_dialog(self)


            return result



    def execute(self, context):

        #print("finished!")
        #print(self.manual_address)

        scene = context.scene
        act_node_ind = scene.cr_node_index
        act_node = scene.cr_nodes[act_node_ind]
        act_node.node_address = self.manual_address
        act_node.node_state = utils.connecting

        bpy.ops.crowdrender.connect_remote_server('INVOKE_DEFAULT')

        return {'FINISHED'}



def load_engine_modules(engine):

    """Load modules required to operate the chosen engine

    """
    # we need to treat blender's internal render engine separately since
    # it is not an addon and therefore is implemented as part of the
    # interpreter.
    from bpy import types
    import sys

    if engine == 'BLENDER_RENDER':
        types.RENDER_PT_render.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_dimensions.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_antialiasing.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_motion_blur.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_shading.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_performance.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_post_processing.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_stamp.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_output.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_bake.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDER_PT_freestyle.COMPAT_ENGINES.add(CROWD_RENDER)
        types.RENDERLAYER_PT_layers.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_context_material.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_custom_props.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_diffuse.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_flare.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_game_settings.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_halo.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_mirror.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_options.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_physics.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_pipeline.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_preview.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_shading.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_shadow.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_specular.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_sss.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_strand.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_transp.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_transp_game.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_volume_density.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_volume_integration.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_volume_lighting.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_volume_options.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_volume_shading.COMPAT_ENGINES.add(CROWD_RENDER)
        types.MATERIAL_PT_volume_transp.COMPAT_ENGINES.add(CROWD_RENDER)

    else:
        try:
            for panel in sys.modules[
                                     settings.engine_modules
                                     [
                                      engine
                                     ]
                                    ].ui.get_panels():

                panel.COMPAT_ENGINES.add(CROWD_RENDER)
        except:
            if engine != 'NONE':
                print("Error: couldn't load ", engine)

#--------------------------end load_engine_modules --------------------------



def register():



    get_ip_class = type('CRENDER_OT_get_local_ip',
                    (cr_discover_local_ip,),
                    {
                    'bl_idname':'crowdrender.get_local_ip',
                    'bl_label': 'get local ip address'

                    }
                        )

    bpy.utils.register_class(CRMain)
    bpy.utils.register_class(open_issue_report)
    bpy.utils.register_class(PackLogs)
    bpy.utils.register_class(get_ip_class)
    bpy.utils.register_class(cr_conn_try_again)
    bpy.utils.register_class(cr_conn_failed)
    bpy.utils.register_class(cr_dummy)
    bpy.utils.register_class(connect_remote_server)
    bpy.utils.register_class(cancel_connect_remote_server)
    bpy.utils.register_class(NetworkErrorOperator)
    bpy.utils.register_class(IncorrectEngineOperator)
    bpy.utils.register_class(ResyncRemoteMachine)
    bpy.utils.register_class(cr_discover_local_ip)
    bpy.utils.register_class(RemCRNode)
    bpy.utils.register_class(AddCRNode)
    bpy.utils.register_class(ConnectNode)
    bpy.utils.register_class(login_cloud)
    bpy.utils.register_class(NodeSettingsDialog)
    bpy.utils.register_class(start_requesting_cloud_insts)
    bpy.utils.register_class(stop_requesting_cloud_instances)
    bpy.utils.register_class(notify_requesting)
    bpy.utils.register_class(cr_open_help)
    bpy.utils.register_class(change_instance_number)
    bpy.utils.register_class(send_connect_msg)
    bpy.utils.register_class(show_load_balancer)
    bpy.utils.register_class(show_discovery_error)
    bpy.utils.register_class(CROWDRENDER_OT_save_your_work)
    bpy.utils.register_class(CR_OT_clear_node_report)
    bpy.utils.register_class(CR_OT_show_node_reports)
    bpy.utils.register_class(CR_OT_show_cloud_issues)
    bpy.utils.register_class(CR_OT_add_cloud_issue)
    bpy.utils.register_class(CR_OT_clear_cloud_issues)
    bpy.utils.register_class(CR_OT_logout_cloud)
    bpy.utils.register_class(CR_OT_save_node_data)
    bpy.utils.register_class(CR_OT_initialise_cip)
    bpy.utils.register_class(CR_OT_render_still)
    bpy.utils.register_class(CR_OT_render_anim)
    # start crowdrender running on host, but only when blender is actually enabling
    # the addon. Blender can in certain circumstances

    if type(bpy.context) is bpy.types.Context:
        bpy.ops.crowdrender.main('INVOKE_DEFAULT')

   #  setup_network()

    #bpy.ops.crowdrender.get_local_ip('INVOKE_DEFAULT')

    #add handlers
    bpy.app.handlers.load_pre.append(load_update_pre_fwd)
    bpy.app.handlers.load_post.append(load_update_post_fwd)
    bpy.app.handlers.save_pre.append(save_update_pre_fwd)
    bpy.app.handlers.save_post.append(save_update_post_fwd)
    bpy.app.handlers.frame_change_pre.append(frame_change_update_fwd)



#     bpy.utils.register_class(choose_eng_class)

def unregister():

    bpy.utils.unregister_class(open_issue_report)
    bpy.utils.unregister_class(PackLogs)
    #bpy.utils.unregister_class(get_ip_class)
    bpy.utils.unregister_class(cr_conn_try_again)
    bpy.utils.unregister_class(cr_conn_failed)
    bpy.utils.unregister_class(cr_dummy)
    bpy.utils.unregister_class(connect_remote_server)
    bpy.utils.unregister_class(cancel_connect_remote_server)
    bpy.utils.unregister_class(NetworkErrorOperator)
    bpy.utils.unregister_class(IncorrectEngineOperator)
    bpy.utils.unregister_class(ResyncRemoteMachine)
    bpy.utils.unregister_class(cr_discover_local_ip)
    bpy.utils.unregister_class(RemCRNode)
    bpy.utils.unregister_class(AddCRNode)
    bpy.utils.unregister_class(ConnectNode)
    bpy.utils.unregister_class(login_cloud)
    bpy.utils.unregister_class(CRMain)
    bpy.utils.unregister_class(NodeSettingsDialog)
    bpy.utils.unregister_class(start_requesting_cloud_insts)
    bpy.utils.unregister_class(stop_requesting_cloud_instances)
    bpy.utils.unregister_class(notify_requesting)
    bpy.utils.unregister_class(cr_open_help)
    bpy.utils.unregister_class(change_instance_number)
    bpy.utils.unregister_class(send_connect_msg)
    bpy.utils.unregister_class(show_load_balancer)
    bpy.utils.unregister_class(show_discovery_error)
    bpy.utils.unregister_class(CROWDRENDER_OT_save_your_work)
    bpy.utils.unregister_class(CR_OT_clear_node_report)
    bpy.utils.unregister_class(CR_OT_show_node_reports)
    bpy.utils.unregister_class(CR_OT_show_cloud_issues)
    bpy.utils.unregister_class(CR_OT_add_cloud_issue)
    bpy.utils.unregister_class(CR_OT_clear_cloud_issues)
    bpy.utils.unregister_class(CR_OT_logout_cloud)
    bpy.utils.unregister_class(CR_OT_save_node_data)
    bpy.utils.unregister_class(CR_OT_initialise_cip)
    bpy.utils.unregister_class(CR_OT_render_still)
    bpy.utils.unregister_class(CR_OT_render_anim)
    #remove handlers
    if load_update_post_fwd in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_update_post_fwd)
    if load_update_pre_fwd in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(load_update_pre_fwd)
    if save_update_pre_fwd in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_update_pre_fwd)
    if save_update_post_fwd in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(save_update_post_fwd)

#     if 'server_interface_process' in globals():
#         server_interface_process.communicate(timeout=1)
#     if 'client_interface_process' in globals():
#         client_interface_process.communicate(timeout=1)

def on_exit():

    # shutdown background processes

    if 'server_interface_process' in globals():
        server_interface_process.terminate()
    if 'client_interface_process' in globals():
        client_interface_process.terminate()
    for task in upload_tasks.values():
        task.temp_folder.cleanup()
        

atexit.register(on_exit)


# @persistent
# def scene_update_fwd(scene):
#     cr_client.track_scene_update(scene)
# #End of scene_update_fwd()

@persistent
def load_update_post_fwd(dummy):


    bpy.ops.crowdrender.main('INVOKE_DEFAULT')


@persistent
def load_update_pre_fwd(dummy):
    # cr_client.track_load_pre(dummy)
    pass

@persistent
def save_update_pre_fwd(dummy):
#     cr_client.track_save_pre(dummy)
    pass


@persistent
def save_update_post_fwd(dummy):
#     cr_client.track_save_post(dummy)
    pass
@persistent
def frame_change_update_fwd(dummy):
#     cr_client.track_frame_change_pre(dummy)
    pass
