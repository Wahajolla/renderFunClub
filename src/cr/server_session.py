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

import sys, bpy, time, json, time, os, subprocess, atexit, signal, platform
from tempfile import TemporaryDirectory
from mathutils import Vector, Euler, Color
from collections import deque
from statistics import median, mean
from contextlib import redirect_stdout
from . import hash_tree, rules, utils, network_engine, config, render
#from . import unit_tests#TODO: Unit testing... generally...
from . utils import MsgWrapper, setup_logging, get_base_app_version
from . utils import handle_generic_except
from . render import create_render_process
from . logging import l_sep, logging_shutdown
from bpy.app.handlers import persistent
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty
import zmq, shutil
import zmq.auth
from zmq.auth.thread import ThreadAuthenticator

import faulthandler

#module constants
MAIN_PROJECT_FILE = 0
crowdrender = sys.modules[__package__]
SESSION_FILES = 1

if platform.system() in ('Darwin', 'Linux'):
    BIG_OOPS_SIGNALS = [
        signal.SIGTERM,
        signal.SIGABRT,
        signal.SIGINT,
        signal.SIGHUP,
        signal.SIGILL,
        signal.SIGABRT,
        signal.SIGSEGV,
        signal.SIGBUS]#,

elif platform.system() == "Windows":
    BIG_OOPS_SIGNALS = [
        signal.SIGTERM,
        #signal.SIGKILL,
        signal.SIGBREAK,
        signal.SIGINT,
        #signal.SIGHUP,
        signal.SIGILL,
        signal.SIGABRT, 
        signal.SIGSEGV,
        #signal.SIGBUS
        ]

####  CREATE CRASH LOGS #####
fault_text_file_path = os.path.expanduser("~") +\
     os.path.normpath("/cr/logging/ssp_faults.txt")

if os.path.exists(fault_text_file_path):
    fault_text_file = open(fault_text_file_path, "wb")
else:
    utils.mkdir_p(os.path.split(fault_text_file_path)[0])
    fault_text_file = open(fault_text_file_path, "wb")

faulthandler.enable(file = fault_text_file)

class CRServerSession :
    """ Client Session Manager
    """
    
    server_key_pub = ''
    server_key_secret = ''
    
    def get_status(self): return self.__status
    
    def set_status(self, value):
                   
        #check if the state is actually a valid one, situations where only 
        
        if not value in utils.states.keys():
            raise ValueError("attempted to set a state that is not valid")
        
        #we only update if the status has changed
        if value != self.__status:
            self.__status = value
            
            self.logger.info("STATUS" + l_sep + " " + str(self.__status))
            
            
            status_msg = MsgWrapper( message = utils.status_update,
                s_uuid = self.session_uuid,
                attributes = {
                    utils.status_update:self.status,
                    utils.machine_uuid:self.machine_uuid,
                    utils.node_uuid:self.machine_uuid}
                    )
        
            self.ssp_cip_pubsub.send_string(json.dumps(status_msg.serialize()))
            
            
    status = property(fget = get_status, fset = set_status)
    # how many times we'll try to get the blend file before giving up
    MAX_RETRIES = 1 
    
    
    def __init__(self):
        
        
        self.resolution_width = 0
        self.resolution_height = 1
        self.resolution_percentage = 2
        # self.last_render_time = 0.0
        # self.last_draw_time = 0.0
        self.render_processes = []
        self.node_name = utils.get_computer_name()
        self.undo_active = False
        
        atexit.register(self.shutdown)
        
        for signum in BIG_OOPS_SIGNALS:
            signal.signal(signum, self.handle_signal)
         
        self.session_uuid = b'' #need to init this here since setting __status will call
                                # code that refers to this
        self.__status = utils.ready
        self.connections = {}
        self.messages = {}
        self.current_frame = 0
        
        self.k = 1.0
        self.t_s = 0.1
        
        
        #have to be careful here, we assume that the session name is the last 
        # item in argv, so long as we are consistent in server_interface in 
        # how we put args into the process start command, we should be ok. JC.
        # HOLD THAT, looks like it was the second last, last one is the module name
        # for some reason?
              
        self.client_uuid = sys.argv[-2]
        
        self.machine_uuid = utils.get_machine_uuid()
        
        self.logger = setup_logging('server_session', 
            base_app = get_base_app_version())
        
        self.setup_network()
        
        self.map_msg_to_function()
        
        # Maps blender operators to our handler functions so we can 
        # respond appropriately to operators that the user has used
        # in their client. 
        
        self.op_handle_funcs = {
            'OBJECT_OT_duplicate':self.duplicate,
            'OBJECT_OT_duplicate_move':self.duplicate,
            'OBJECT_OT_delete':self.delete,
            'MESH_OT_primitive_cube_add':self.add,
            'MESH_OT_primitive_plane_add':self.add,
            'MESH_OT_primitive_cylinder_add':self.add,
            'MESH_OT_primitive_uv_sphere_add':self.add,
            'MESH_OT_primitive_ico_sphere_add':self.add,
            'MESH_OT_primitive_cone_add':self.add,
            'MESH_OT_primitive_torus_add':self.add,
            'MESH_OT_primitive_grid_add':self.add,
            'MESH_OT_primitive_monkey_add':self.add,
            'MESH_OT_landscape_add':self.add,
            'OBJECT_OT_material_slot_add':self.mat_slot_add,
            'OBJECT_OT_material_slot_remove':self.mat_slot_remove,
            'MATERIAL_OT_new':self.mat_add_new,
            'ED_OT_undo':self.undo_history_exec,
            'ED_OT_redo':self.undo_history_exec,
            'SCENE_OT_render_layer_add':self.render_layer_add,
            'TRANSFORM_OT_translate':self.transform,
            'TRANSFORM_OT_resize':self.transform,
            'TRANSFORM_OT_rotate':self.transform,
            'SCENE_OT_new':self.add_scene
                                }
                                
        self.undo_array = list()
        
        self.logger.info( 'started logging on ' + __name__)
        self.logger.info(' Client uuid is ' + self.client_uuid)
        self.logger.info("Machine UUID" + l_sep + " " + self.machine_uuid)
        
        self.rules = rules.CRRules()
        self.keep_alive = True
        #Call to keep this process alive 
        self.server_session_process()
    
######## INIT_SESSION METHODS ##########################################################
    
    def init_session(self, msg = None):
        """ Causes a session to be initialised
        
        This method operates to initialised a  session, whether this is a saved
        session being loaded from disk, or a completely new session. It opens or saves 
        the cip blend file, configures the zmq sockets and creates directory structures
        where necessary.
    
        """
        
        machine_uuid = msg.attributes[utils.machine_uuid]
        
        # if this wasn't meant for us then ignore it
        if not machine_uuid == self.machine_uuid: return
        
        self.upload_task = msg.attributes[utils.upload_task]
        
        resyncing = msg.attributes[utils.resync]
        
        self.session_files = self.upload_task[SESSION_FILES]
        self.load_trusted = msg.attributes[utils.load_trusted]
        self.logger.debug("CRServerSession.init_session:" + l_sep +\
            "Load trusted set to: " +\
            str(self.load_trusted))
        
        #set status to syncing
        self.status = utils.syncing
        
        
        #cancel any file transfers 
        
        cancel_msg = MsgWrapper(command = utils.cancel,
            attributes ={})
        
        self.file_req_sock.send_json(cancel_msg.serialize())
        
        
        ##### CHECK IF BLEND FILE EXISTS #####
        
        if hasattr(self, 'blend_file'):
        
            # make sure the path actually exists
            if os.path.exists(self.blend_file): 
                
                #Save the file to capture changes to the previous session
                # before loading the new session.
                self.logger.info("CRServerSession.init_session:" + l_sep +\
                        'saving before loading new session')
                bpy.data.use_autopack = False# avoids errors where 
                    #autopack cannot find files.
                
                bpy.ops.wm.save_as_mainfile(
                    filepath = self.blend_file, 
                    compress=False)
        
        self.session_uuid = msg.s_uuid
        self.client_top_hash = msg.attributes[utils.top_hash]        
        
        self.cr_path = utils.get_cr_path()
        self.session_path = self.cr_path + os.path.normpath(
            '/' + self.session_uuid.decode('utf-8'))
        
        #Need to check whether this is a new session or not.
        blend_file_name = self.session_files[MAIN_PROJECT_FILE]
            
        #We make the local file by concatenating the session directory with 
        # just the name of the blend file as it is on the user's client.
        # any changes to the file name will cause a separate file to be uploaded
        # though. 
        self.blend_file = os.path.join(
            self.session_path,
            os.path.basename(blend_file_name)
            )
        
        #if resyncing we need to force the upload of the file. 
        if resyncing:
            
            self.retrieve_blend_file(retry = 0)
        
        # If this session does exist we need to make sure that its data
        # is the same or not.
        elif os.path.exists( self.session_path):
            
            #If the path exists, then we try to open it, should the open fail, the
            # method called below will initiate a new file transfer which will 
            # result in another call to the open_blend_file method until MAX_RETRIES 
            # is reached and then we give up.
            
            if os.path.exists(self.blend_file):
                    
                self.open_blend_file(MsgWrapper(command = utils.open_blend_file,
                                attributes= {utils.retry:0}))
                                
            else:
                
                self.retrieve_blend_file(retry =0)
                
             
        else:
            # if the path doesn't exist, assume this is a new session and create a 
            #directory structure for it. 
            
            self.logger.info("CRServerSession.init_session:" + l_sep +\
                'New session, creating directory and files')
                
            utils.mkdir_p( self.cr_path + os.path.normpath(
                '/' + self.session_uuid.decode('utf-8')) )
         
            self.retrieve_blend_file(retry = 0)
            
        self.temp_dir = TemporaryDirectory(dir = self.session_path)
        self.output_path = self.temp_dir.name
          
        
    def retrieve_blend_file(self, retry=10): 
        
        """ 
            Use the dealer/router channel to request and receive the .blend 
            file from the client interface.  
            
        NOTE: if retry is not given then the default value is to set it to the 
        maximum number of retries so that the system will not loop infinitely.   
        
        """                   
        
        self.status = utils.uploading
        
        get_file_msg = MsgWrapper(
            command = utils.file_transf_req, 
            s_uuid = self.session_uuid,
            attributes = {
                utils.file_path:(self.session_files[MAIN_PROJECT_FILE], 
                self.blend_file),
                utils.retry:retry,
                utils.command:utils.open_blend_file,
                utils.cancelled_command:utils.cancel_upload,
                utils.node_uuid:self.file_requester.server_router_id}
            )
        
        
        self.file_req_sock.send_json(get_file_msg.serialize())
        
        upload_task_begin_msg = MsgWrapper(
            message = utils.upload_task_begin,
            s_uuid = self.session_uuid,
            attributes = {
                utils.upload_task:self.upload_task,
                utils.node_uuid:self.machine_uuid
                })
        
        self.ssp_cip_pubsub.send_string(
            json.dumps(
                upload_task_begin_msg.serialize()
                    )
            )
        
        
    def open_blend_file(self, msg):
        """ Open and check the blend file with n retries
        
        This method accepts a msg in the following format:
        
        msg = MsgWrapper(command = string, attributes = {})
        Any contents can be placed in the string or {} arguments for the MsgWrapper.
        In the context of the server_session, they are used for giving a function/
        method to call after retrieving a file. The funciton will be this function and 
        the attributes will be the number of sequential retries allowed, in this case
        the value of the class variable MAX_RETRIES is used.        
        
        """
        
        # of course actual retries left is one more than the requested since we 
        # 'spend' one retry entering the loop.
        
        retry = msg.attributes[utils.retry]
        
        if retry > self.MAX_RETRIES:
            self.logger.warning("CRServerSession.open_blend_file: " + l_sep +\
                "attempted to open the blend file " + str(retry + 1) +\
                " times, but ultimately this failed")
        else:
            
            retry += 1
            
            try:
            
                bpy.ops.wm.open_mainfile(
                    filepath = self.blend_file, 
                    load_ui=False,
                    use_scripts = self.load_trusted)
                                        
                self.make_hash_tree()
                    
            except:
                
                
                location = "CRServerSession.open_blend_file"
                log_string = "Error when trying to open the blend file"
                
                
                handle_generic_except(log_string, location, self.logger)
                
                backup_blend_file = os.path.join(os.path.split(self.blend_file)[0], 
                    'svr_old.blend')
                
                bpy.ops.wm.save_mainfile(filepath = backup_blend_file)
                
                try:
                    
                    os.remove(self.blend_file)
                    
                    
                except FileNotFoundError:
                    
                    self.logger.warning("CRServerSession.open_blend_file: " + l_sep +\
                        "Attempted to remove the blend file: " +\
                        self.blend_file + " but this file couldn't be found.")
                        
                
                self.status = utils.sync_failed
                
                
              
    def make_hash_tree(self):
        """ Builds the hash tree, checks and sets sync status accordingly
            
    Arguments: 
        none
    Returns:
        int - 1 if the operation completed successfully, 0 otherwise 
    Side Effects:
        Loads the render performance data for the associated session-uuid and 
        updates the client with this information
    Exceptions:
        none
    Description:
        This is the final method in the sequence of initialising the server session. 
        The hash tree is built from the loaded data and checked with the client's 
        value. If they match, the method returns 1, sets status to 'synced' and also
        loads the render performance data for the session_uuid, if there is any.
        
        """
        
        
        self.logger.info("CRServerSession.make_hash_file: " +l_sep +\
             " file is now loaded, checking hash values")
        
        self._hash_tree = hash_tree.CRHashTree(bpy.data, self.rules)
        
        self.logger.info("CRServerSession.make_hash_file: " +l_sep +\
             "top hash on server's scene is " + \
            str(self._hash_tree.top_hash) + " top hash on client's scene is:" +\
            str(self.client_top_hash) )  
        
        if not self._hash_tree.top_hash == self.client_top_hash:
            
            #remove the damaged file, we need to save the now open file to 
            # another name since on windows, attempting to delete it will
            # raise an error. 
            
            msg_str = ("CRServerSession.make_hash_file: " +l_sep +\
                "hash files did not match. Setting status to sync fail : " +\
                str(self.blend_file))
                
            self.logger.info(msg_str)
            
            self.status = utils.sync_failed
            
            self.hash_tree_check()
            
            upload_task_fin = MsgWrapper(
                message = utils.upload_task_complete,
                s_uuid = self.session_uuid,
                attributes ={
                    utils.upload_task:self.upload_task,
                    utils.node_uuid:self.machine_uuid}
                                         )
            
            self.ssp_cip_pubsub.send_string(
                json.dumps(
                    upload_task_fin.serialize()))
            #if there are retries left, we can try again, if not then we exit
            return 0
            
        else:
            #if the hash values match then we're ok to begin the session. 
            self.status = utils.synced
            
            upload_task_fin = MsgWrapper(
                message = utils.upload_task_complete,
                s_uuid = self.session_uuid,
                attributes ={
                    utils.upload_task:self.upload_task,
                    utils.node_uuid:self.machine_uuid}
                                         )
            
            self.ssp_cip_pubsub.send_string(
                json.dumps(
                    upload_task_fin.serialize()))
            
            self.undo_array.append(self._hash_tree.top_hash)
            bpy.ops.ed.undo_push()
            self.undo_active = False
            
            # load the corresponding render performance data and report this to the client
            
            #sets K and t_s for this session
            self.get_load_balance_variables(bpy.context.scene.render.engine)
            
            update_render_stats = MsgWrapper(
                message = utils.update_render_stats,
                    attributes =    {
                        utils.k:self.k,
                        utils.t_s:self.t_s  
                                    }
                            )
            
            reset_file_upload_progress = MsgWrapper(
                message = utils.progress_update,
                s_uuid = self.session_uuid,
                attributes = {
                    utils.node_uuid:self.machine_uuid,
                    utils.percent_complete:0
                    }
                )
                
                
            self.ssp_cip_pubsub.send_string(
                json.dumps(
                    update_render_stats.serialize()))
            
            self.ssp_cip_pubsub.send_string(
                json.dumps(
                    reset_file_upload_progress.serialize()))
            
            return 1
            
            
######## END INIT_SESSION METHODS ######################################################        
    
    def update_local_address(self, msg=None):
    
        import ipaddress
        
        addresses = list()
    
        binding_addresses = network_engine.discover_local_ip()
        
        for addr_info in binding_addresses:
            
            addr = addr_info[0]
            
            try: 
                address = ipaddress.ip_address(addr)
                
                if address.version == 6: 
                    self.logger.info("not using IPv6 addresses, skipping : " + str(addr))
                    continue # not interested in 
                    addresses.append(address)
            except ValueError:
                self.logger.info("not a valid address, skipping : " + str(addr))
                continue
            
            
            ##  
            
            
            
        return addresses
        
    
    def setup_network(self):
        # Define the sockets required to communicate with client        
        self.context = zmq.Context() 
        
        #Set up Authentication options
        auth = ThreadAuthenticator(self.context)
        auth.start()        
        # Tell the authenticator how to handle CURVE requests
        auth.configure_curve(domain='*', location=zmq.auth.CURVE_ALLOW_ANY)
        
        #Create the certificates
        conf_path = os.path.normpath(os.path.expanduser("~/cr/.conf"))
        cert_path = os.path.join(conf_path, '.certificates/server')
        if os.path.exists(cert_path):
            shutil.rmtree(cert_path)
        os.makedirs(cert_path)
                
        serv_pub_file, serv_secret_file = \
            zmq.auth.create_certificates(cert_path, "server_session")
        
        self.server_key_pub, self.server_key_secret = \
            zmq.auth.load_certificate(serv_secret_file) 
        
        #TODO - CR-38, Ummmm dynamic ports? what will all the other remote processes use?
        # Also we desperately need to do error checking on the calls to any zmq function, 
        # bind, connect, you name it.
        user_preferences = bpy.context.preferences
        addon_prefs = user_preferences.addons[crowdrender.package_name].preferences
        
        self.start_port = addon_prefs.start_port
        self.port_range = addon_prefs.port_range
        self.network_timeout = float(addon_prefs.network_timeout)

            
        # # Connection for PUB_SUB Server Interface Process to Server_Session_Process
        self.sip_ssp_pubsub = self.context.socket(zmq.SUB) #port 9023
        self.sip_ssp_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.sip_ssp_pubsub.connect('tcp://127.0.0.1:' + str(self.start_port + 7)) # old port 9023')
        self.sip_ssp_pubsub.setsockopt(zmq.SUBSCRIBE,b'')
        self.connections['sip_ssp_pubsub'] = self.sip_ssp_pubsub
        
        #TODO:JIRA:CR-38 Implement a method of configuration of 
        # the sockets/connections that allows for multiple connections
        self.cip_ssp_pubsub = self.context.socket(zmq.SUB)    #port 9003    
        self.cip_ssp_pubsub.setsockopt(zmq.SUBSCRIBE,b'')
        self.cip_ssp_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.cip_ssp_pubsub.curve_secretkey = self.server_key_secret
        self.cip_ssp_pubsub.curve_publickey = self.server_key_pub
        self.cip_ssp_pubsub.curve_server = True
        self.cip_ssp_pubsub.bind("tcp://*:" + str(self.start_port + 3))
        self.connections['cip_ssp_pubsub'] = self.cip_ssp_pubsub
        
        self.ssp_sip_pubsub = self.context.socket(zmq.PUB) #port 9024
        self.ssp_sip_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.ssp_sip_pubsub.bind("tcp://127.0.0.1:" + str(self.start_port + 8)) # old port 9024")
        self.connections['ssp_sip_pubsub'] = self.ssp_sip_pubsub
        
        self.ssp_cip_pubsub = self.context.socket(zmq.PUB) #port 9051
        self.ssp_cip_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.ssp_cip_pubsub.curve_secretkey = self.server_key_secret
        self.ssp_cip_pubsub.curve_publickey = self.server_key_pub
        self.ssp_cip_pubsub.curve_server = True
        self.ssp_cip_pubsub.bind("tcp://*:" + str(self.start_port + 10))
        self.connections['ssp_cip_pubsub'] = self.ssp_cip_pubsub        
        
        self.render_thread_sock_addr = 'render_thread'
        self.render_thread_sock = self.context.socket(zmq.SUB)
        self.render_thread_sock.subscribe(b'')
        self.render_thread_sock.bind("inproc://" + self.render_thread_sock_addr)
        self.connections['render_thread'] = self.render_thread_sock
        
        self.file_req_addr = 'file_request_channel'
        self.file_req_sock = self.context.socket(zmq.PAIR)
        self.file_req_sock.bind("inproc://" + self.file_req_addr)
        self.connections['file_req_sock'] = self.file_req_sock
        
        self.file_serv_addr = 'file_server_channel'
        self.file_serv_sock = self.context.socket(zmq.PAIR)
        self.file_serv_sock.bind("inproc://" + self.file_serv_addr)
        self.connections['file_serv_sock'] = self.file_serv_sock
        
        
        # Initialize poll set for the receiving ports only
        self.poller = zmq.Poller()
        self.poller.register(self.sip_ssp_pubsub , zmq.POLLIN)
        self.poller.register(self.cip_ssp_pubsub , zmq.POLLIN)
        self.poller.register(self.file_req_sock, zmq.POLLIN)
        self.poller.register(self.render_thread_sock, zmq.POLLIN)
              
        
        
    def server_session_process(self):       
        
        while(self.keep_alive):
        
            #time.sleep(10)
                                    
            self.process_msgs()
        
    def process_msgs(self):
    
        #sometimes this is put in a 'try/except handler'
        #the timeout is in milliseconds
        
        try:
        
            socks = dict(self.poller.poll(10))
        
            if self.cip_ssp_pubsub in socks:
            
                cip_ssp_pubsub_message = MsgWrapper.deserialize( 
                    self.cip_ssp_pubsub.recv_string())
            
                msg_uuid = cip_ssp_pubsub_message.attributes[utils.message_uuid]
                # avoid duplicate messages due to TCP retransmit on pub sub socks
                if msg_uuid in self.messages: pass
                
                else:
                
                    self.messages[msg_uuid] = cip_ssp_pubsub_message 
                
                    self.logger.debug("receiving cip_ssp_pubsub msg")
            
                    if cip_ssp_pubsub_message.command in self.msg_map:
            
                        self.logger.info(cip_ssp_pubsub_message.command)
            
                        func = self.msg_map[cip_ssp_pubsub_message.command]
                        #TODO:JIRA:CR-50 Need to be consistent in our interface, we are here
                        # calling func as if there is one positional argument, see below, 
                        # we call func using a keyword argument, both are used to pass the
                        # message object into the handling function, but the different syntax
                        # causes bugs if the dev gets mixed up.
                
                        func(cip_ssp_pubsub_message)
                #now process the message if self.sip_ssp_pubsub_message in self.msg_map:
                    
                    elif cip_ssp_pubsub_message.message in self.msg_map:
                        
                        self.logger.info(cip_ssp_pubsub_message.message)
                        
                        func = self.msg_map[cip_ssp_pubsub_message.message]
                        #TODO:JIRA:CR-50 Need to be consistent in our interface, we are here
                        # calling func as if there is one positional argument, see below, 
                        # we call func using a keyword argument, both are used to pass the
                        # message object into the handling function, but the different syntax
                        # causes bugs if the dev gets mixed up.
                
                        func(cip_ssp_pubsub_message)
        
            #!!! Important, we must process the sip_ssp_pubsub last of all
            # since this is the channel we transmit the exit message on.
            # Once we have receieved the exit message, all sockets and pollers
            # are removed meaning attempting to check any sockets from this point
            # on will raise an error.
        
            if self.sip_ssp_pubsub in socks:
            
                self.logger.debug("receiving sip_ssp_pubsub message")
            
                sip_ssp_pubsub_message = MsgWrapper.deserialize(
                                    self.sip_ssp_pubsub.recv_string())

                 #now process the messageif self.sip_ssp_pubsub_message in self.msg_map:
                if sip_ssp_pubsub_message.command in self.msg_map:
    #             
                    func = self.msg_map[sip_ssp_pubsub_message.command]
    #             
                    func(msg = sip_ssp_pubsub_message)
                
            if self.file_req_sock in socks:
            
                msg = MsgWrapper.deserialize(self.file_req_sock.recv_json())
            
                command = msg.command
                message = msg.message
            
                if not command ==  "": 
                    func = self.msg_map.get(command)
                
                    func(msg)
                
                elif not message == "":
                    func = self.msg_map.get(message)
                
                    func(msg)
                
                
            if self.render_thread_sock in socks:
            
                 #the renderthread only sends stats, so we merely pass the msg
                # on, no need to decode it.
                msg = self.render_thread_sock.recv_string()
                self.ssp_cip_pubsub.send_string(msg)
                
                unserial_msg = MsgWrapper.deserialize(msg)
                
                #cleanup and log
                if unserial_msg.message == utils.finished_view:
                    
                    self.logger.info("Received " + unserial_msg.message +\
                                    " message.")
                    
                elif unserial_msg.message == utils.finished_tile:
                    
                    self.status = utils.synced
                    for proc in self.render_processes:
                        stdout, stderr = proc.communicate()
                    self.render_processes.clear()
                    self.logger.info("Received " + unserial_msg.message +\
                                    " message" + l_sep + " Setting status to "+\
                                    " synced " + l_sep + str(utils.synced))
                
                    self.k = unserial_msg.attributes.get(utils.k, 1.0)
                    self.t_s = unserial_msg.attributes.get(utils.t_s, 0.1)
                
                elif unserial_msg.message == utils.render_failed:
                
                    self.render_processes.clear()
                    self.status = utils.synced
                    self.logger.warning("CRServerSession.process_msgs" +\
                        "render failed, heres the error msg: "+\
                        l_sep.join(unserial_msg.attributes[utils.error_message])
                        )
                
                
                
        except zmq.ZMQError as e:
            if e.errno == zmq.EAGAIN: 
                pass
            
            else:
                self.logger.warning("zmq error whilst trying to recv a connect" +\
                    "request :"  + e.strerror)
                
        except IndexError:
    
            location = "CRServerMachineManager.process_msgs"
            log_string = """Oddly shaped packet received on 
            cipr_sip_reqrouter socket: """
            
            handle_generic_except(location=location, 
                                  log_string= log_string,
                                  logger=self.logger)
        
        except: 
            location = "CRServerMachineManager.process_msgs"
            log_string = """unexpected error when processing msg
             received on cipr_sip_reqrouter socket: """
            handle_generic_except(location=location, 
                                  log_string=log_string,
                                  logger=self.logger)
                
                
    def handle_signal(self, signum, frame):
        
        self.logger.error(
            "Received signal: " + str(signum) + ", shutting down")
        self.logger.error(
            "Frame from signal: " + str(frame))
        self.shutdown()
        
        
    def disconnect(self, msg = None):
    
        assert utils.machine_uuid in msg.attributes
        
        #all nodes get a message to shutdown, but only one message is actually for this
        # node, next version of crowdrender will fix this nonsense!
        if not self.machine_uuid == msg.attributes[utils.machine_uuid]:
            return
        
        self.shutdown(msg)    
            
                
    def shutdown(self, msg = None):
        #TODO:JIRA:CR-51 Let the Parent SSP know that we have been commanded to shutdown
        
        #set status to exited, will automatically send notification to the cip.
        self.status = utils.exited
        
        self.temp_dir.cleanup()
        
        # Log that we're exiting
        self.logger.info('Shutting down, saving file...')
        
        #bpy.ops.wm.save_mainfile()
        
        # Command the server interface process to shutdown
        # self.sip_ssp_pubsub.send_string(utils.exit)
        exit_msg = MsgWrapper(command = utils.exit,
            s_uuid = self.session_uuid,
            attributes={})
        self.file_req_sock.send_json(exit_msg.serialize())
        self.file_serv_sock.send_json(exit_msg.serialize())
    
        self.file_requester.join(timeout = 2.0)
        self.file_server.join(timeout = 2.0)
        
        self.poller.unregister(self.sip_ssp_pubsub)
        self.poller.unregister(self.cip_ssp_pubsub)
        
        #shut down the network interfaces and zmq.context        
        for name, socket in self.connections.items():
            self.logger.info('closing : ' + name)
            socket.close(linger=0)
                
        self.context.term()
        #Cause our main while loop to exit        
        self.keep_alive = False
        
        #now the local log
        self.logger.info('Server Session is shutting down') 
        
        logging_shutdown()
        
        ########   SHUTDOWN   ##############
        
    def file_recv_cancelled(self, msg):
        
        self.status = utils.ready
        
        self.logger.info("CRServerSession.file_recv_cancelled" + l_sep +\
            "File recieve task was cancelled for file: " +\
             str(msg.attributes[utils.file_path])
             )
        
        
    def file_received(self, msg):
        
        self.file_received = True
        
    def file_server_down(self, msg):
        #shutting the node down cause we can't contact the file server
        # need to aleart client to this fact!
        self.logger.warning("Shutting down as I can't contact the fileserver")
        self.shutdown()
    
    def map_msg_to_function(self):
        
        self.msg_map = {
            utils.exit:self.shutdown,
            utils.run_unit_tests:self.handle_unit_test,
            utils.data_update:self.handle_sync_update,
            utils.client_address_update:self.update_client_address,
            utils.local_address_update:self.local_address_update,
            utils.render:self.render,
            utils.init_session:self.init_session,
            utils.render_eng_update:self.update_render_engine,
            utils.disconnect:self.disconnect,
            utils.get_nodes_by_uuid:self.check_nodes,
            utils.get_node_attrib_hashes:self.check_node_attribs,
            utils.file_received:self.file_received,
            utils.file_server_down:self.file_server_down,
            utils.hello:self.handle_hello,
            utils.hello_ssp:self.handle_ssp_hello,
            utils.cancel_render:self.cancel_render,
            utils.open_blend_file:self.open_blend_file,
            utils.make_hash_tree:self.make_hash_tree,
            utils.recv_fail:self.handle_file_recv_fail,
            utils.progress_update:self.send_transfer_prog,
            utils.cancel_upload:self.cancel_upload
            }
    
    def cancel_upload(self, msg):
        """ Cleanup on cancelling an upload
        """
        
        self.status = utils.ready
        
    
    def handle_file_recv_fail(self, msg):
        """ Should the file request fail for any reason, set status appropriately
        """
        self.status = utils.sync_failed
        
    
    def send_transfer_prog(self, msg):
        """ Notify the client of the % file received during a transfer
        
        Arguments:
            msg: -  
                string  
                    A json formatted string representing a MsgWrapper object
                    that contains the follwing:
                    
                    t_uuid - the task uuid
                    s_uuid - the session uuid
                    attributes:
                        {utils.percent_complete:    float - % recvd,
                        utils.node_uuid:            string - sending node uuid
                        }
        
        Returns:
            nothing
            
        Side Effects: 
            Sends a msg to the client informing it of the 
            % progress of file transfer, it also changes the status 
            code to 'uploading'
            
        Exceptions Raised:
            None.
            
        Description:
            This method is part of the feedback loop during 
            file uploads that reports the progress of the upload 
            to a node on a 0-100% scale. 
                                
        """
        msg.attributes[utils.status] = utils.uploading
        
        self.ssp_cip_pubsub.send_string(json.dumps(msg.serialize()))
                    
    def handle_ssp_hello(self, msg):
        """ Respond to a hello msg, used when establishing connections
        """
        response_msg = MsgWrapper(message = utils.ssp_alive,
                            s_uuid = msg.s_uuid,
                            attributes = {utils.machine_uuid:self.machine_uuid,
                                        utils.client_uuid:self.client_uuid})
                            
        self.ssp_sip_pubsub.send_string(json.dumps(response_msg.serialize()))
        
        self.logger.info("responding to sip initiated hello request..")
        
        
    def handle_hello(self, msg):
        """ Respond to a hello msg, used when establishing connections
        """
        if not self.machine_uuid == msg.attributes[utils.machine_uuid]:
            self.logger.info("CRServerSession.handle_hello: " + l_sep +\
                            " Ignoring hello for : " +\
                            str(msg.attributes[utils.machine_uuid]))
        else:
                            
            response_msg = MsgWrapper(message = utils.hello,
                attributes = {utils.machine_uuid:self.machine_uuid})
                            
            self.ssp_cip_pubsub.send_string(json.dumps(response_msg.serialize()))
        
            self.logger.info("CRServerSession.handle_hello: " + l_sep +\
                    "responding to hello request from client..")
        
        
        
                        
    def handle_init_request (self, msg = None):
        
        #check the top hash initialised on the client side with that
        # initialised here. If it isn't the same, transfer the file from
        # the client to server and retry building the hash tree.
        
        client_top_hash = msg.attributes[utils.top_hash]
            
        if client_top_hash == self._hash_tree.top_hash:
            return
        else:
            self.log('initial hash values not a match, requesting a file transfer')
            #code to get file
            
            #Code to build a new hash tree for the new file.
                             
    
    def render(self, msg = None):
    
        if utils.machine_uuid in msg.attributes:
            
            machine_uuid = msg.attributes[utils.machine_uuid]
            
            #if this wasn't meant for us, ignore
            if not machine_uuid == self.machine_uuid: return
            
            
            self.status = utils.rendering
            
            scene_name = msg.attributes.get(utils.scene, "")
            scene = bpy.data.scenes.get(scene_name)
            
            if scene is not None:
            
                bpy.context.window.scene= scene
            
            
            # update render stats to set them to zero
            update_msg = MsgWrapper(message = utils.render_stats, 
                t_uuid = msg.t_uuid,
                attributes = {
                utils.render_stats:[[0, "starting..."]],
                utils.machine_uuid:self.machine_uuid,
                utils.state:utils.rendering})
            self.ssp_cip_pubsub.send_string(json.dumps(update_msg.serialize()))
        
        views = msg.attributes[utils.views]
        samples = msg.attributes[utils.eng_samples]
        engine = msg.attributes[utils.render_engine]
        img_output_fmt = msg.attributes[utils.img_output_fmt]
        
        #set render engine to the requested engine, this must be done to prevent
        # connecting nodes from setting their render engine to 'crowdrender'
        
        #bpy.context.scene.render.engine = engine
        
        self.logger.info("Going to render using : " + str(engine))
        
        self.update_render_settings(msg)
        
        
        coords = msg.attributes[utils.screen_coords]
        node = msg.attributes[utils.nodes][self.machine_uuid]
        tile_x = node[utils.tile_x]
        tile_y = node[utils.tile_y]
        compute_device = node[utils.compute_device]
        compute_devices = node[utils.compute_devices]
        threads = node[utils.process_threads]
        exr_codec = msg.attributes[utils.exr_codec] 
        load_trusted = msg.attributes[utils.load_trusted]
        output_path = os.path.join(
            self.output_path, scene_name + "_" + self.machine_uuid)
        
        
        self.current_frame = msg.attributes[utils.current_frame]
        start_frame, end_frame = msg.attributes[utils.frame_range]
        is_animation = msg.attributes[utils.is_animation]
         
        bpy.data.use_autopack = False
        
        if not is_animation:
        
            self.logger.info("saving main file")
        
            bpy.ops.wm.save_as_mainfile(filepath = self.blend_file, compress= False)
            
        elif is_animation and self.current_frame == start_frame:
            
            self.logger.info("saving main file")
        
            bpy.ops.wm.save_as_mainfile(filepath = self.blend_file, compress=False)
            
        else:
            self.logger.info("Rendering frame :" + str(self.current_frame) +\
                " without saving blend file")
        
        self.logger.info("starting render process")
        
        ## CREATE RENDER PPROCESS
            
        process = create_render_process(
            self.load_trusted, coords, tile_x, 
            tile_y, compute_device, compute_devices, threads,
            self.blend_file, output_path, engine, img_output_fmt, 
            self.current_frame, exr_codec,
            self.logger, scene_name)
            
        self.render_processes.append(process)
        
        render.CRRenderThread(
            msg.t_uuid, 
            self, 
            self, 
            process, 
            self.current_frame, 
            coords,
            msg.attributes[utils.screen_res], 
            engine, 
            samples, 
            views = views)
        
        
        
        
    def cancel_render(self, msg):
        """ does what it says on the tin...
        """
        
        # if this is the local machine, just kill the process that is currently
        # rendering, or all of them if there's more than one. 
        
            
            
            
        for proc in self.render_processes:
            
            proc.kill()

            try:
                stdout, stderr = proc.communicate(timeout = 1)
            except:
                self.logger.error("CRServerMachine:cancel_rendering:" +\
                                     "error when trying to cancel render proc.")
                
            
        self.status = utils.synced
        self.render_processes.clear()
        
        # for remote nodes, send the cancel msg.    
    
    def update_render_settings(self, msg = None):
    
        R = bpy.context.scene.render
        
        R.resolution_x = msg.attributes[utils.screen_res][self.resolution_width]
        R.resolution_y = msg.attributes[utils.screen_res][self.resolution_height]
        R.resolution_percentage = msg.attributes[utils.screen_res][self.resolution_percentage]
        
      
    def update_render_engine(self, msg = None):
        
        
        
        engine = msg.attributes[utils.render_engine]
        
        self.logger.info('Changing the render engine to :' + engine)
        
        bpy.context.scene.render.engine = engine
        
        self.logger.info('Render engine changed to :' + \
                bpy.context.scene.render.engine)
        
    
    def update_client_address(self, msg = None):
        
                
       
        local_addresses = msg.attributes[utils.local_address]
        client_machine_uuid = msg.attributes[utils.machine_uuid]
        access_key = msg.attributes[utils.access_key]
        
        self.session_uuid = msg.s_uuid
        
        self.get_load_balance_variables('CYCLES') #Making the assumption that most
        # will want to use cycles, though in 2.8 this will have to change to EEVEE 
        # probably since eevee is the default engine on opening blender 2.8
        
        #override the machine uuid if this is a cloud based instance running on virtual 
        # hardware
        if access_key != '':
            self.logger.info("CRServerSession.update_client_address: " +\
                " overriding machine uuid with supplied access_key: " +\
                str(access_key))
            self.machine_uuid = access_key
                
        
        
        self.file_requester = network_engine.CRFileRequest(
                                           'server_node',
                                           self.logger, 
                                           self.context,
                                           self.machine_uuid,  
                                           self.file_req_addr,
                                           server_router_id = client_machine_uuid,
                                           local_addresses = local_addresses,
                                           timeout = self.network_timeout,
                                           start_port = self.start_port,
                                           port_range = self.port_range,
                                           local_public_key = self.server_key_pub,
                                           local_sec_key = self.server_key_secret
                                           )
                                           
        self.file_server = network_engine.CRFileServer(
                                            'server_node',
                                            self.logger, 
                                            self.context,
                                            self.file_serv_addr, 
                                            self.machine_uuid, 
                                            self.start_port, 
                                            self.port_range, 
                                            self.network_timeout,
                                            local_addresses= local_addresses,
                                            local_public_key = self.server_key_pub,
                                            local_sec_key = self.server_key_secret
                                            )   
                                                   
        # send all available endpoints to the client and let it decide which it can
        # connect to.
        
        endpoints = {utils.file_requester_ep:self.file_requester.endpoints,
                    utils.file_server_ep:self.file_server.endpoints}
                
        ready_msg = MsgWrapper(message = utils.ready,
                            s_uuid = msg.s_uuid,
                            public_key = self.server_key_pub,
                            attributes = {utils.server_endpoint:endpoints,
                                        utils.machine_uuid:self.machine_uuid,
                                        utils.client_m_uuid:client_machine_uuid,
                                        utils.k:self.k, 
                                        utils.t_s:self.t_s})
        
        self.ssp_sip_pubsub.send_string(json.dumps(
                                            ready_msg.serialize(),
                                            cls = utils.BTEncoder
                                            ))
    
    def local_address_update(self, msg):
        
        
        local_address = msg.attributes[utils.local_address]
        
        ssp_cip_router_dealer_addr = self.ssp_cip_router_dealer.LAST_ENDPOINT.decode(
                                                                                'utf-8')
        
        ssp_cip_pubsub_addr = self.ssp_cip_pubsub.LAST_ENDPOINT.decode('utf-8')
        
        if not local_address in ssp_cip_pubsub_addr:
            self.logger.info("Changing local address to " + local_address)
            if not ssp_cip_pubsub_addr =='':
                self.ssp_cip_pubsub.unbind(ssp_cip_pubsub_addr)
            self.ssp_cip_pubsub.bind(
                        "tcp://" + local_address + str(self.start_port + 10) ) #":9051")
            
        else:
            self.logger.info("Change of address requested but new address was the same" +\
                            ", keeping the old address")
                
        if not local_address in ssp_cip_router_dealer_addr:
            if not ssp_cip_router_dealer_addr =='':
                self.ssp_cip_router_dealer.unbind(ssp_cip_router_dealer_addr)
            
            self.cip_ssp_router_dealer.bind(
                        "tcp://" + local_address + str(self.start_port + 12) ) #":9065")
            
        else:
            self.logger.info("Change of address requested but new address was the "+\
                "same, keeping the old address")
                
    def process_attribute_updates(self, node_uuid, attributes):
        """ Processes an update to an attribute of the node argument
        """
        
        
        node = self._hash_tree.nodes_by_uuid.get(node_uuid)
        
        if node is not None:
        
        
            self.mod_attributes(node, attributes)

            self._hash_tree.update_node(initialising = False, node_uuid = node.uuid)

            self.logger.info("server top hash is: " + str( self._hash_tree.top_hash))
            
        else:
            
            self.logger.info("CRServerSession.process_attribute_updates" + \
                l_sep + "Could not find: " + node_uuid)
        
        
        
    def handle_sync_update(self, sync_update):
        """Handle an update to the data and set status depending on result
        """
                
        self.status = utils.syncing
        
        self.logger.info("Client top hash is: " + str(self._hash_tree.top_hash))
                      
        node_uuid = ''
        
        active_scene_client = sync_update.attributes.get(utils.scene, "")
        active_scene = bpy.data.scenes.get(active_scene_client)
        
        #change to the correct scene
        if active_scene is not None: bpy.context.window.scene = active_scene
                
        if utils.sync_manifest in sync_update.attributes:
            # node_uuid = sync_update.attributes[utils.node_uuid]
            #process a list of data blocks/CRHashTreeNodes
        
            # Handle property updates to existing nodes here.
            for node_uuid, attributes in sync_update.attributes[utils.sync_manifest].items():
            
                self.process_attribute_updates(node_uuid, attributes)
            
            
        else:
            node_uuid = sync_update.attributes.get(utils.node_uuid, '')
        
        if utils.operator in sync_update.attributes:
            operator = sync_update.attributes[utils.operator]
            self.logger.info("Going to attempt operator " + operator)
            
        else: operator = None 
        
        #Check if we're handling a node that already exists
        if node_uuid in self._hash_tree.nodes_by_uuid:
        
            node = self._hash_tree.nodes_by_uuid[node_uuid]
        
        
        
            # Handle a duplication, note this is hard coded for testing at
            # the moment, we need a more sophisticated switching algorithm
            # to determine what the operator was and take the correct action.
            
            if operator:
            
            
            # We need to select the duplicated object. We need the
            # filter to be case sensitive and setting extend to false
            # means that if any other objects have remained selected#
            # they will be deselected so that only the matching object
            # is a member of the selection after the operator runs.
            
                bpy.ops.object.select_pattern(
                                              pattern=node.name, 
                                              case_sensitive = True,
                                              extend = False
                                              )
                                              
                self.logger.info("Operating on " + node_uuid)
                
                if operator in self.op_handle_funcs.keys():
                    # run the function indexed by the 'operator' attribute of the
                    # sync update object.
                    func = self.op_handle_funcs[operator]
                    
                    func(node, sync_update)
                
                else:
                    self.logger.info('Unknown Operation received. Ignoring')
                
#                 self._hash_tree.update_node(initialising = False, node_uuid = node.uuid)
                
                self.logger.info('Server Session top hash value = ' +\
                     str(self._hash_tree.top_hash))
            
            
                                              
            
        #Handle additions and  (of new nodes) here
        else:
          
            if operator:
                
                #TODO:JIRA:CR-52 baaaaaaad, how do we know for sure that
                # only additions will make it here? What some other
                # operator were to be processed in this block that 
                # could call a handler that expects and needs a 
                # parent node?
           
                func = self.op_handle_funcs[operator]
                
                func(None, sync_update)
                
                #bpy.context.scene.update()
                
                self.logger.info('Server Session top hash value = ' +\
                    str(self._hash_tree.top_hash))
                
            else:
                # So, the node isn't in the tree and there's no operator eh?
                # you are screwed then! Sync failed an you've no idea why?!
                
                self.logger.warning(
                    "There was no operator or the node could be processed "+\
                    " for a data update. Node: " + str(node_uuid))
        
        if self._hash_tree.top_hash == sync_update.attributes[utils.top_hash]:
            
            
            
            if self.undo_active and not(operator=='ED_OT_undo' or operator=='ED_OT_redo'):
            
                self.undo_active = False
                
                
                
                # Clear remainder of undo array since we've started a new undo history
                # from this point on.
                while(len(self.undo_array) > self.undo_history_index + 1):
                #for i in range(self.undo_history_index + 1, len(self.undo_array)):
                    self.undo_array.pop()
                
                self.undo_array.append(self._hash_tree.top_hash)
                bpy.ops.ed.undo_push()
                    
                self.status = utils.synced
                # Need to return here since we have popped to a previous undo level
                # we do not want to push an undo level here. 
                
                 
                
                return
                
            elif self.undo_active and (operator=='ED_OT_undo' or operator=='ED_OT_redo'):
                
                
                
                self.status = utils.synced
                # Need to return here since we have popped to a previous undo level
                # we do not want to push an undo level here. 
                
                return
                
            else:
            
                self.logger.info("BINGO")
                
                self.undo_array.append(self._hash_tree.top_hash)

                # hack! Blender does not keep an undo history in background mode. trying
                # to create one by pushing undo's manually.
                bpy.ops.ed.undo_push()
                
                self.status = utils.synced
            
            
        else:
            self.status = utils.sync_failed
            
            self.logger.warning("Server session top hash is :" +\
                 str(self._hash_tree.top_hash) )
                 
            self.logger.warning("The client's top hash is :" +\
                 str(sync_update.attributes[utils.top_hash]) )
                   
        
        
        
        
        # not all data updates are mods which result in a valid node.
        if self.status == utils.sync_failed:
            
            
            #request the client's nodes_by_uuid collection to compare trees
            #self._hash_tree.walk(logger = self.logger) # toooo much log data!
            self.hash_tree_check()
    

    def get_load_balance_variables(self, engine):
        """ Find K and Ts values for the current session
        
        Arguments: 
            engine - string - name of the render engine being used. Must match 
                                that used internally by blender
        
        Returns: 
            None
        
        Exceptions:
            None
        
        Side Effects:
                Reads relevant data from the conf file and sets values for
                k and t_s.
                
        Description:
            This function extracts the relvant render performance data, k and Ts which are
            the performance coefficient and the setup time. K has units of seconds per 
            pixel sample, and Ts has units of seconds.
            
            The load balancer requires these values to estimate the optimal screen area to
            assign to each node before rendering a frame. This data is segmented by 
            session uuid and render engine, this is because different files often  
            have very differnt render times as do different render engines, so we don't 
            mix the data between them.               
        """
        
        s_uuid = self.session_uuid.decode('utf-8')
        
        perf_data = utils.read_config_file([config.node_perf_data])
        
        self.logger.info("Reading load balance variables")
        
        data = perf_data[config.node_perf_data].get(s_uuid)
        
        if data is not None and isinstance(data, dict): # added additional check for 
                                        # data being of type dict for older versions 
                                        # storing incompatible data in a list
                                        
            eng_data = data.get(engine)
            if eng_data is not None:    
                self.t_s = eng_data[1]
                k_all = eng_data[0]
                self.k = mean(k_all) #store and send only mean value of K
            
            # The session exists but the engine hasn't been used on this scene before
            else:
                self.k = 1.0
                self.t_s = 0.1
        # No data at all for this session.  
        else:
            self.k = 1.0
            self.t_s = 0.1
            
            
    
    def check_node_attribs(self, msg):
    

        nodes_data = msg.attributes[utils.node_uuid]
        machine_uuid = msg.attributes[utils.machine_uuid]
        client_top_hash = msg.attributes[utils.top_hash]
        
        type_map = {str:StringProperty(), int:IntProperty(), float: FloatProperty(),
                        bool: BoolProperty()}
        
        
        #dont react to requests not meant for this node.
        if not machine_uuid == self.machine_uuid:
            return
        
        # no point continuing if the node isn't even in the tree,
        # this is an error to fix since the request should not even
        # have generated this response from the client if the node isn't
        # in the tree.
        
        for node_uuid, node_data in nodes_data.items():                     
            
            if not node_uuid in self._hash_tree.nodes_by_uuid:
                self.logger.error("Node: " + node_uuid + " not found in hash tree")
                repair_msg = MsgWrapper(message = utils.repair_item,
                s_uuid = msg.s_uuid,
                attributes = {utils.node_uuid:self.machine_uuid,
                            utils.status:utils.repairing,
                            utils.repair_item:"",
                            utils.missing_block:node_uuid,
                            utils.repair_message:"Missing datablock"}
                                )
                self.ssp_cip_pubsub.send_string(json.dumps(repair_msg.serialize()))
                continue
            
            attrib_hashes = node_data[utils.attribute_hashes]
            attributes = node_data[utils.attributes]            
            
            server_node = self._hash_tree.nodes_by_uuid[node_uuid]
            server_node_hashes = server_node.attrib_hashes
            
            #blacklist any attributes we have that are not in the 
            serv_attr = self.rules.get_attribs(server_node.data)
            
            bl_attr = [k for k in serv_attr.keys() \
                          if k not in attributes.keys()]
            
            self.logger.info('Adding the following items to blacklist : '+\
                                  str(bl_attr))
            
            self.rules.black_list.update(bl_attr)
            
            for attr, hash_value in attrib_hashes.items():
            
                if attr not in server_node_hashes:
                    #somehow we have an attribute we're missing,
                    # add it and move on. 
                
                    self.logger.info('Adding attribute :' + attr + ' with value:' + str(attributes.get(attr)))
                    
                    attr_type = type_map[type(attributes.get(attr))]
                    
                    setattr(type(self._hash_tree.nodes_by_uuid[node_uuid].data), attr, attr_type)
                    setattr(self._hash_tree.nodes_by_uuid[node_uuid].data, attr, attributes.get(attr))
                    
                    self._hash_tree.update_node(initialising = False, node_uuid = node_uuid)
                
                    #The missing attributes should now have been corrected
                    # If the hashes are correct send a positive message otherwise
                    # send a sync failed message
                    
                    check_attrib = (self._hash_tree.nodes_by_uuid[node_uuid].data.get(attr) == attributes.get(attr))
                    
                    #update the user on the progress of the repair of the tree  
                    self.logger.info("node :" + node_uuid + " was missing attribute :" +\
                        attr + ' :: Fixed :' + str(check_attrib))
                        
                    repair_msg = MsgWrapper(message = utils.repair_item,
                    s_uuid = msg.s_uuid,
                    attributes = {utils.node_uuid:self.machine_uuid,
                                utils.status:utils.repairing,
                                utils.repair_item:server_node.name,
                                utils.repair_attr:attr,
                                utils.repair_message:"Missing attribute"}
                                    )
                    
                    
                                        
                    self.ssp_cip_pubsub.send_string(json.dumps(repair_msg.serialize()))
            
                #if we find an attribute with the wrong hash value we log it.
                
                server_node = self._hash_tree.nodes_by_uuid[node_uuid]
                server_node_hashes = server_node.attrib_hashes
                client_node_data_hash = sum(attrib_hashes.values())
                
                if not hash_value == server_node_hashes.get(attr):
            
                    self.logger.debug("node :" + node_uuid +\
                         " has bad hash value for " +\
                        "attribute :" + attr)
                    
                    self.logger.debug("server has value :" +\
                            str(server_node_hashes.get(attr)) +\
                            " whereas the client has value :" + str(hash_value))
                        
                    self.logger.info("attempting to repair bad attribute value...")
                
                    try:
                        #Set attr to the correct value and rehash the node.
                        setattr(server_node.data, attr, 
                                attributes.get(attr))
    
                        self.logger.info('updated: ' + attr)                    

                        self._hash_tree.update_node(initialising=False,\
                                                    node_uuid=server_node.uuid)
                    
                        if server_node.data_hash_value != client_node_data_hash:
                            self.logger.debug("data hash does not match for: " +\
                                node_uuid + ": hash values are: " +\
                                str(client_node_data_hash) + ":"  +\
                                str(server_node.data_hash_value) )
                            repair_msg = MsgWrapper(message = utils.repair_item,
                                s_uuid = msg.s_uuid,
                                attributes = {utils.node_uuid:self.machine_uuid,
                                utils.status:utils.repairing,
                                utils.repair_item:server_node.name,
                                utils.repair_attr:attr,
                                utils.repair_message:"Incorrect Data"})
                            self.ssp_cip_pubsub.send_string(
                                json.dumps(repair_msg.serialize()))
                    
                        if self._hash_tree.top_hash == client_top_hash:
                        
                            self.status = utils.synced
                        
                            return # if we're synced no need to continue
                    
                        else:
                        
                            self.logger.info("repaired attribute: " + attr +\
                                " but the hash tree is still not synced.")

        
                    except:
        
                        err_data = sys.exc_info()
        
                        self.logger.error("Modification of the " +\
                            attr +\
                                        " for the data " + str(server_node.data) +\
                                        " failed.")
                                    
                        self.logger.error(str(err_data[0]) + " " + str(err_data[1])) 
                        
                        err_msg = MsgWrapper(message = utils.repair_item,
                                s_uuid = msg.s_uuid,
                                attributes = {utils.node_uuid:self.machine_uuid,
                                utils.status:utils.sync_failed,
                                utils.repair_item:server_node.name,
                                utils.repair_attr:attr,
                                utils.repair_message:"Unable to Sync"})
                                
                        self.ssp_cip_pubsub.send_string(
                                json.dumps(err_msg.serialize()))
                            
        #Ideally the hash_tree has been repaired by the time we get here
        if self._hash_tree.top_hash == client_top_hash:
            self.status = utils.synced
        else:    
            self.status = utils.sync_failed                 
   
        
    def check_nodes(self, msg):
    
        nodes_by_uuid = msg.attributes[utils.nodes_by_uuid]
        machine_uuid = msg.attributes[utils.machine_uuid]
        
        #dont react to requests not meant for this node.
        if not machine_uuid == self.machine_uuid:
            return
        
        nodes_to_request = []
        
        
        for node_uuid, client_hashes in nodes_by_uuid.items():
        
            if not node_uuid in self._hash_tree.nodes_by_uuid:
            
            
                err_msg = "MISSING " + node_uuid.split("::")[-1] 
            
                self.logger.debug("Node :" + node_uuid +\
                            " not found in hash tree!")
                            
                repair_msg = MsgWrapper(message = utils.repair_item,
                s_uuid = msg.s_uuid,
                attributes = {utils.node_uuid:self.machine_uuid,
                            utils.status:utils.repairing,
                            utils.repair_item:err_msg}
                                )
            
                self.ssp_cip_pubsub.send_string(json.dumps(repair_msg.serialize()))
                            
            else:
                
                servers_node = self._hash_tree.nodes_by_uuid[node_uuid]
                
                #if the hash_value matches then this node is synced, move on.
                if servers_node.hash_value == client_hashes[0]:
                    continue 
                    
                else:
                    
                    if not servers_node.data_hash_value == client_hashes[1]:
                        
                        
                        nodes_to_request.append(node_uuid)
                        #request the attributes of the node so we can 
                        # report which one is causing the problem
                        
                        
                    else:
                        # continue, we are looking for the node where the data_hash_value
                        # is different between client and server. 
                        continue
                        
        rqst_attrib_hashes = MsgWrapper(
                s_uuid = self.session_uuid,
                command = utils.get_node_attrib_hashes,
                attributes = {utils.machine_uuid:self.machine_uuid,
                                utils.node_uuid:nodes_to_request}
                                                )
                                                
        self.ssp_cip_pubsub.send_string(json.dumps(
                            rqst_attrib_hashes.serialize()))
    
                 
    def hash_tree_check(self):
        """ Send a rqst to the client to get its list of nodes.

        This kicks of an interrogation of the differences between the two hash 
        trees which should result in the data that is different being logged
        to the server session log file. Using this data it should be possible
        to nail down the exact cause of the fault.
        
        """
        
        self.status = utils.repairing
    
        #msg to the client to get hash_tree nodes
        rqst_nodes = MsgWrapper(command = utils.get_nodes_by_uuid,
            s_uuid = self.session_uuid,
            attributes = {utils.machine_uuid:self.machine_uuid})
        
        self.ssp_cip_pubsub.send_string(json.dumps(
                                            rqst_nodes.serialize()))
                                            
            
    def handle_unit_test(self, message = None):
    
        # try:
                       
        pass#unit_tester = unit_tests.CRUnitTests('SERVER SESSION', self)
            
        # except:
            # self.logger.error('Could not run unit tests, failed to instance the tester')
        
    def duplicate(self, node, sync_update):

        # Run the operator, which is stored as a string, so we use
        # exec to execute the string as if it were a command typed 
        # at the prompt. 
        
        #In duplicate, we need to select the second last object, since this was
        # the one that was copied.
        
        attributes = sync_update.attributes
        original_nodes = {}
        
        try:
            
            
            bpy.ops.object.select_all(action='DESELECT')
            
            for node_uuid in attributes[utils.previously_selected]:
                
                original_node = self._hash_tree.nodes_by_uuid[ node_uuid ]
                
                original_nodes[node_uuid] = original_node
                
            
                bpy.ops.object.select_pattern(
                              pattern= original_node.name, 
                              case_sensitive = True,
                              extend = True
                                              )
            
            operator = self.rules.bl_id_2_operator[ attributes[utils.operator] ]
            
            
            operator() 
            
            
            
        except Exception as inst:
            
            tb = sys.exc_info()[2]
            
            self.logger.error(" :: " + str(type(inst)))
            self.logger.error(" :: " + str(inst.args))
            
            raise Exception().with_traceback(tb)
        # Now that we have duplicated the object, we need to update
        # our hash tree and create a new node for it at the right lvl.
        
        # Since we know that the object added will be in the same
        # collection as that from which is was duplicated, we can 
        # 
        # data, parent, hash_tree, hash_rules=rules.CRRules):
        
        original_node_uuid, original_node = original_nodes.popitem()
        
        
        try:
            duplicated_data_blocks = bpy.context.selected_objects
            
            # set location, rotation and scale data
            
            for data_block in duplicated_data_blocks:
                
                new_node = hash_tree.CRHashTreeNode(
                
                                        data_block,

                # Here we must add the right parents to the new duplicated node
                # so it 'knows' where it is in the tree. Not doing this correctly
                # can lead to problems deleting the node or duplicating, searching
                # hashing and so on. 
                
                                        original_node.parents[0],                                                
                                        self._hash_tree,
                                        hash_rules = self.rules
                                                
                                                    )
                
                uuid = new_node.uuid
                
                data_block.location = attributes[utils.duplicated_nodes][uuid]['location']
                
                data_block.rotation_euler = attributes[utils.duplicated_nodes][uuid]['rotation']
                
                data_block.scale = attributes[utils.duplicated_nodes][uuid]['scale']
                                        
            # TODO:JIRA:CR-54 RISK: we are assuming here that the node only has one parent,
            # while this is fine for object nodes, it isn't for other types 
            # of nodes, such as a mesh node. We'll need to tread carefully
            # to make sure that mesh node duplications are handled gracefully
            # cause right now they aren't!
            
            
            # TODO: JIRA CR-30: Are we restricting our case here to that where the node has
            # only one parent? 
            
                new_node.parents[0].children.append(new_node)                
            
                self._hash_tree.update_node(initialising=False, node_uuid=new_node.uuid)
            
        except Exception as inst:
        
            tb = sys.exc_info()[2]
            
            self.logger.error(" :: " + str(type(inst)))
            self.logger.error(" :: " + str(inst.args))
            
            raise Exception().with_traceback(tb)
        
        
        
        
    def delete(self, node, sync_update):
        
        # Run the operator, which is stored as a string, so we use
        # exec to execute the string as if it were a command typed 
        # at the prompt. 
        
        attributes = sync_update.attributes
        
        nodes_to_remove = []
        
        try:
            
            bpy.ops.object.select_all(action='DESELECT')
            
            for data_ptr, node_uuid in attributes[utils.previously_selected].items():
                
                node = self._hash_tree.nodes_by_uuid.get( node_uuid )
               
            
                bpy.ops.object.select_pattern(
                              pattern= node.name, 
                              case_sensitive = True,
                              extend = True
                                              )
                
                # call our code to remove the node associated with the
                # deleted object.
                
                if not node is None:
                    nodes_to_remove.append(node_uuid)
                
            
            operator = self.rules.bl_id_2_operator[ attributes[utils.operator] ]
            
            
            operator()
            
            self._hash_tree.delete_node(node_uuid = nodes_to_remove)
                  
        
        except Exception as inst:
            
            tb = sys.exc_info()[2]
            
            self.logger.error(" :: " + str(type(inst)))
            self.logger.error(" :: " + str(inst.args))
            
            raise Exception().with_traceback(tb)
        
        # tree_root_uuid = self._hash_tree.tree_root.uuid
#             
#         self._hash_tree.update_node(initialising=False, node_uuid=tree_root_uuid)
        
        
    def add(self, node, sync_update):
                       
        # object_pointer = node.data.as_pointer()
        
        parent_node_uuid = sync_update.attributes[utils.parent_node_uuid]
        
        parent_node = self._hash_tree.nodes_by_uuid[parent_node_uuid]
        self.logger.info(parent_node.name)
        
        #get the operator
        
        operator = self.rules.bl_id_2_operator[
                sync_update.attributes[utils.operator]
                ]
        
        # Call the blender operator so that blender
        # deletes its data for this object
        
        operator()
        
        added_data_block = bpy.context.active_object
        
        # set location, rotation and scale data
        
        if added_data_block is not None:
        
            added_data_block.location = sync_update.attributes['location']
            added_data_block.rotation_euler = sync_update.attributes['rotation_euler']
            added_data_block.scale = sync_update.attributes['scale']
            
            self._hash_tree.update_node(initialising=False, node_uuid=parent_node_uuid)
            
        else:
            
            self.status = utils.sync_failed
        
        
    def mod_attributes(self, node, attributes):
        """ modify the attributes assoc with the node's data object
        """
        
        self.logger.info("modding attributes of " + node.uuid)
        
        self.logger.info(attributes[utils.value])
        
        # get a reference to the nodes data object
        node_data = node.data

        try:
            setattr(node_data, attributes[utils.attributes], 
                        attributes[utils.value])
        
            self.logger.info('updated ' + attributes[utils.attributes])
            
        except:
            
            location  = "CRServerSession.mod_attributes"
            
            log_string = "Modification of the " +\
                 attributes[utils.attributes] +\
                " for the data " + str(node_data) + " failed."
            
            handle_generic_except(location, log_string, self.logger)                
        
      
        
        
        #TODO:JIRA:CR-55 Think search data is the wrong thing to do here, need to 
        # calculate the hash, not look for other items.
        node.search_data([], initialising=False)
        
             
        
        self.logger.info(str(getattr(node.data, 
                        attributes[utils.attributes])))
        # self.logger.info(node_attr)
        
        #self.logger.info(self._hash_tree.top_hash)
        
        # Aggregate hashes
        
        # self._hash_tree.tree_root.aggregate_hash_values()
        
    def add_scene(self, node, sync_update):
        """ Add a new scene
        """
        
        sc_type = ['NEW', 'EMPTY', 'LINK_OBJECTS', 'LINK_OBJECT_DATA', 'FULL_COPY']
        
        operator = self.rules.bl_id_2_operator[
                    sync_update.attributes[utils.operator]
                    ]
        
        operator(type = sc_type[sync_update.attributes[utils.scene_add_type]])
        
        bpy.context.scene.name = sync_update.attributes[utils.scene]
        
        
        parent_node = self._hash_tree.tree_root
                                               
        new_node = parent_node.insert_child_node(
                                        data=bpy.context.scene
                                                    )
                                                    
        self._hash_tree.update_node(initialising=False, node_uuid=parent_node.uuid)
        
        
    def mat_slot_add(self, node, sync_update):
        """ add a material slot to the selected object
        """
        try:
        
            operator = self.rules.bl_id_2_operator[
                    sync_update.attributes[utils.operator]
                    ]
                    
            operator()
            
            #we need to call search_data with the init flag set to true to cope 
            # with the fact that for some reason, blender changes the memory address
            # of the material_slots when you add a new one!
            
            node.search_data([], initialising=True)
            
            
                    
        except Exception as inst:
            
            tb = sys.exc_info()[2]
            
            self.logger.error(" :: " + str(type(inst)))
            self.logger.error(" :: " + str(inst.args))
            
#             raise Exception().with_traceback(tb)        
        
    def mat_slot_remove(self, node, sync_update):
        """ Remove the active material slot from the active object
        """
        
        try:
            #set active material index
            bpy.context.active_object.active_material_index = sync_update.attributes[
                                                                utils.active_mat_ind]
            
            #run the operators (should be the bpy.ops.object.material_slot_remove() )
            
            operator = self.rules.bl_id_2_operator[
                    sync_update.attributes[utils.operator]
                    ]
                    
            operator()
            
            node.search_data([], initialising=True)
                    
        except Exception as inst:
            
            tb = sys.exc_info()[2]
            
            self.logger.error(" :: " + str(type(inst)))
            self.logger.error(" :: " + str(inst.args))
            
#             raise Exception().with_traceback(tb)
            
    def mat_add_new(self, node, sync_update):
    
        #get materials properties/attributes
        
        use_nodes = sync_update.attributes[utils.use_nodes]
    
        try:
        
            
            # we're going to add a material, so lets take a snapshot of the
            # current materials.
            
            current_materials = set(bpy.data.materials.keys())
            
            # make sure we have the right material slot selected
            
            # if there are no material slots, we'll need to add one. 
            if len(bpy.context.active_object.material_slots) == 0:
                
                #create the new slot and then get the index for it
                bpy.ops.object.material_slot_add()
                
                active_material_index = bpy.context.active_object.active_material_index
                
                active_mat_slot = bpy.context.active_object.material_slots[active_material_index]
            
            # otherwise, we use the index of the user's session for the 
            # active material slot they chose to place this new material in.
            else:
                
                active_material_index = sync_update.attributes[
                                    utils.active_mat_ind]
                
                bpy.context.active_object.active_material_index = active_material_index
                
                active_mat_slot = bpy.context.active_object.material_slots[active_material_index]
            
            
            # get the operator and run it
            operator = self.rules.bl_id_2_operator[
                    sync_update.attributes[utils.operator]
                    ]
                    
            operator()
            
            new_materials = set(bpy.data.materials.keys())
            
            new_material_name = new_materials - current_materials
            
            #new material name is a set, we need to string value from inside!
            new_mat_name = new_material_name.pop()
            
            # set material properties/attributes
            bpy.data.materials[new_mat_name].use_nodes = use_nodes
            
            #Link the new material to the node,
            active_mat_slot.material = bpy.data.materials[new_mat_name]
             
            
            #TODO:JIRA:CR-56 rather in-efficient since we'll be completely blowing away the 
            # entire hash tree below this node, better to find the affected node and 
            # only destroy that branch. Avoids unnecessary re-parsing of vertex, edge, 
            # polys.
            
             
            node.search_data([], initialising=True)
            
            
                    
        except Exception as inst:
            
            tb = sys.exc_info()[2]
            
            self.logger.error(" :: " + str(type(inst)))
            self.logger.error(" :: " + str(inst.args))
            
            # no longer raise the exception, log it and move on!
#             raise Exception().with_traceback(tb)
            
            
    def undo_history_exec(self, node, sync_update):
    
        
        client_top_hash = sync_update.attributes[utils.top_hash]
        
        
       
        try:
            self.undo_active = True
            # look up which undo history item we need to move to
            undo_index = self.undo_array.index(client_top_hash)
            
            self.undo_history_index = undo_index
            #debug
            self.logger.info(str(self.undo_array))
            self.logger.info("undo index is " + str(undo_index))
            
             # Execute the undo
            bpy.ops.ed.undo_history(item=undo_index)
            
            self._hash_tree.parse_main(bpy.data, rebind=True)
            
            
            
        except Exception as inst:
            
            tb = sys.exc_info()[2]
            
            self.logger.error(" :: " + str(type(inst)))
            self.logger.error(" :: " + str(inst.args))
            self.logger.error(str(self.undo_array))
            #CR-147 when the undo history is incorrect its better
            # that we let the server go into syncfail so it can be recovered 
            # rather than just raise an unhandled exception and let it crash the 
            # process.
            #raise Exception().with_traceback(tb)
            
    
    def render_layer_add(self, node, sync_update):
    
        layer_name = sync_update.attributes[utils.render_layer_name]
        self.logger.info("adding a render layer with the name : " + str(layer_name))
        bpy.context.scene.render.layers.new(layer_name)
        active_scene_name = bpy.context.scene.name
        
        self._hash_tree.update_node(False, '_BlendData::'+\
                               active_scene_name+\
                            '_Scene::_RenderSettings')
    
    def transform(self, node, sync_update):
        """ handles transform updates
        
        Arguments:
            node:          Hash tree node   -   A link to the hash_tree node to be adjusted.
            sync_update:   MsgWrapper       -   The update message received from the CIP
        
        Returns:
            nothing
        
        Side Effects:
            Should transform the requested node using the given LocRotScale data in sync_update
            
        Exceptions:
            none
        
        Description:
           This function uses a message received from the CIP to affect a particular object 
           in the scene by perform location, rotation or scale operations as requested in the
           sync_update message.
        """
        
        attributes = sync_update.attributes
        for node_uuid, transform_data in attributes[utils.transform_vector].items():
            node_data = self._hash_tree.nodes_by_uuid.get(node_uuid)
            if node_data is not None:
                node_data.data.location = transform_data['location']
                node_data.data.rotation_euler = transform_data['rotation']
                node_data.data.scale = transform_data['scale']
                self._hash_tree.update_node(initialising=False, node_uuid=node_uuid)