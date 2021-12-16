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

import bpy, time, zmq, uuid, argparse, atexit, signal
import sys, json, ipaddress, subprocess, threading, queue
from . import utils, network_engine, config, render
from . rules import get_cycles_devices, get_compute_devices
from . utils import timed_out, get_computer_name, get_crowdrender_version
from . utils import  setup_logging, MsgWrapper, CRWebRequest, get_base_app_version
from . utils import handle_generic_except, profile_func
from . config import write_config_file, read_config_file
from . render import create_render_process
from . logging import l_sep, logging_shutdown
from . network_engine import CHUNK_SIZE
from math import exp
from statistics import mean
import shutil, zmq.auth
from zmq.auth.thread import ThreadAuthenticator

import os   #was this already done 

import faulthandler
from zmq.error import ZMQError

####  CREATE CRASH LOGS #####
fault_text_file_path = os.path.expanduser("~") +\
     os.path.normpath("/cr/logging/cip_faults.txt")

if os.path.exists(fault_text_file_path):
    fault_text_file = open(fault_text_file_path, "wb")
else:
    utils.mkdir_p(os.path.split(fault_text_file_path)[0])
    fault_text_file = open(fault_text_file_path, "wb")

faulthandler.enable(file = fault_text_file)



### CREATE LOGGER FOR THIS MODULE
logger = setup_logging('client_interface', base_app = get_base_app_version())

TIMEOUT = 5.0 #seconds
crowdrender = sys.modules[__package__]
ERROR_SHARING_VIOLATION = 32 
SESSION_FILES = 1
MAIN_PROJECT_FILE = 0
#https://docs.microsoft.com/en-us/windows/desktop/debug/system-error-codes--0-499-


class CRCloudLogin(threading.Thread):
    """ Thread based class to handle making HTTP requests
    
    This class uses the requests module to make HTTP requests in a 
    thread separate to the main branch of execution allowing non-
    blocking requests. 
    """
    #TODO: Change name to CRHTTPRequest
    
    def __init__(self, c_s_manager, request):
        
        threading.Thread.__init__(self)
        
        socket_endp = c_s_manager
        
        self.timeout = c_s_manager.network_timeout
        
        self.sock = c_s_manager.context.socket(zmq.DEALER)
        self.sock.connect('inproc://' + c_s_manager.login_threads_sock_addr)
        self.request = request
        self.uuid = request[utils._uuid]
        
        
        self.start()
        
    def run(self):
    
        import requests
        
        payload = self.request[utils.payload]
        url = self.request[config.url_api]
        headers = self.request[utils.headers]
        request_type = self.request[utils.http_request_type]
        
        data = json.dumps(payload)
        
        
        # This is a non_json request. We're using just a string, don't json encode
        # the body/payload, use a different request class. 
        try:
            response = requests.request(request_type, url, data=payload, 
                                    headers=headers, timeout = self.timeout )
                                    
            resp_msg = utils.MsgWrapper(message = utils.request_response,
                attributes = {utils.request_response:response.json(),
                                utils._uuid:self.uuid})
                
            self.sock.send_string(json.dumps(resp_msg.serialize()))
                                    
        except requests.exceptions.Timeout:
        
            resp_msg = utils.MsgWrapper(message = utils.request_response,
                attributes = {utils._uuid:self.uuid,
                    utils.request_response:utils.timed_out})
                
            self.sock.send_string(json.dumps(resp_msg.serialize()))
            
            
        
        #self.sock.disconnect('inproc://login_threads')
        self.sock.close()

class CRContactServer(threading.Thread):
    
    def __init__(self, c_s_manager, connect_data, sess_uuid):
        threading.Thread.__init__(self, daemon= True)
        #setup the sockets
        
        self.sess_uuid = sess_uuid
        self.c_s_man = c_s_manager
        self.node_name = connect_data[utils.node_name]
        self.machine_uuid = self.c_s_man.machine_uuid
        self.REQUEST_TIMEOUT = self.c_s_man.network_timeout * 1000 # poll requires millisecs
        self.REQUEST_RETRIES = 1
        self.CLIENT_REQUEST_TIMEOUT = 10
        self.node_address = connect_data[utils.node_address]
        self.SERVER_ENDPOINT = "tcp://" + self.node_address +\
            ":" + str(self.c_s_man.start_port + 6) # old port":9022"
        self.access_key = connect_data[utils.access_key]
        self.session_uuid = c_s_manager.session_uuid
#         self.file_server_addr = c_s_manager.local_address +\
#                         ":"+\
#                         str(c_s_manager.file_server.router_port)
        
        self.context = c_s_manager.context
        self.logger = c_s_manager.logger
        self.success_handler = c_s_manager.server_connect
        self.try_again_handler = c_s_manager.try_again
        self.failure_handler = c_s_manager.server_no_connect
        self.logger.info("CRContactServer.__init__" + l_sep + " Connecting to server...")
        self.client = self.context.socket(zmq.REQ)
        self.client.connect(self.SERVER_ENDPOINT)
        
        self.connector_inproc = self.context.socket(zmq.DEALER)
        self.connector_inproc.connect("inproc://connector")
        #create an inproc socket to connect to the main thread
        # remember that you have to bind to the parent's socket 
        # before connecting inside this thread.

        self.pollserver = zmq.Poller()
        self.pollserver.register(self.client, zmq.POLLIN)
        
        self.pollclient = zmq.Poller()
        self.pollclient.register(self.connector_inproc, zmq.POLLIN)
        
        self.retries_left = self.REQUEST_RETRIES
        
        self.start()
        
    def run(self):
        
        while self.retries_left:
            
            request = MsgWrapper(command = utils.connection_req, 
                            attributes = {
                                  utils.session_uuid:self.session_uuid.decode('utf-8'),
                                  utils.machine_uuid:self.machine_uuid,
                                  utils.access_key:self.access_key
                                          }
                                        )
            
            self.logger.info("CRContactServer.__init__" + l_sep +\
                 " Sending (%s)" % request.command)
            self.client.send_string(
                            json.dumps(request.serialize(), 
                            cls = utils.BTEncoder))
            
            
            
            expect_reply = True
            
            while expect_reply:
            
                serversocks = dict(self.pollserver.poll(self.REQUEST_TIMEOUT))
                clientsocks = dict(self.pollclient.poll(self.CLIENT_REQUEST_TIMEOUT))
                
                try:
                
                    if clientsocks.get(self.connector_inproc) == zmq.POLLIN:
                        
                        msg_raw = self.connector_inproc.recv_string()
                    
                        msg = MsgWrapper.deserialize(msg_raw)
                        
                        if msg.command == utils.cancel_connection:
                            #get outta here! the user wants to cancel!
                            
                            
                            self.logger.info("CRContactServer.run" + l_sep +\
                                " User requested cancel, cancelling...")
                            # since we're aborting, close all sockets, they're no longer
                            # needed
                            
                            break 
                            
                            
                
                    if serversocks.get(self.client) == zmq.POLLIN:
                
                        reply_raw = self.client.recv_string()
                        reply = MsgWrapper.deserialize(reply_raw)
                    
                         # Success!
                        if reply.message == utils.ready:
                        
                            # Add the address to the attributes so that we can find
                            # the pending connection and remove it later
                        
                            reply.attributes[utils.node_address] = self.node_address
                        
                            self.logger.info("CRContactServer.run" + l_sep +\
                                " Server replied OK (%s)" % reply.attributes)
                            self.retries_left = 0#self.REQUEST_RETRIES
                            self.connector_inproc.send_string(json.dumps(reply.serialize(), 
                                cls = utils.BTEncoder))

                        
                            break
                        
                        else:
                            self.logger.error("CRContactServer.run" + l_sep +\
                                " Malformed reply from server: %s" % reply)
                            fail_msg = MsgWrapper(message = utils.connect_failed,
                                                s_uuid = self.sess_uuid,
                                    attributes = {utils.node_address:self.node_address,
                                                utils.node_name:self.node_name
                                                }
                                    )
                            self.connector_inproc.send_string(json.dumps(fail_msg.serialize(), 
                                cls = utils.BTEncoder))
                        
                            break
                            
                    else:
                    
                        
                        
                        self.retries_left -= 1
                    
                        if self.retries_left == 0:
                            self.logger.warning("CRContactServer.run" + l_sep +\
                                " Server seems to be offline, abandoning")
                            fail_msg = MsgWrapper(message = utils.connect_failed,
                                                s_uuid = self.sess_uuid,
                                attributes = {utils.node_address:self.node_address,
                                                utils.node_name:self.node_name}
                                                )
                                
                            self.connector_inproc.send_string(json.dumps(fail_msg.serialize(), 
                                cls = utils.BTEncoder))
                        
                            break
                            
                        else:
                    
                            self.logger.info("CRContactServer.run" + l_sep +\
                                "Reconnecting and resending (%s)" % request.command)
                            try_again_msg = MsgWrapper(message = utils.trying_again,
                                            s_uuid = self.sess_uuid,
                                attributes={utils.node_name:self.node_name}
                                )
                            self.connector_inproc.send_string(json.dumps(try_again_msg.serialize()))
                            # Create new connection
                            self.client = self.context.socket(zmq.REQ)
                            self.client.connect(self.SERVER_ENDPOINT)
                            self.pollserver.register(self.client, zmq.POLLIN)
            
                            self.logger.info("CRContactServer.run" + l_sep +\
                            " Sending (%s)" % request.command)
                            self.client.send_string(
                                    json.dumps(request.serialize(), 
                                    cls = utils.BTEncoder))
                                
                except zmq.ZMQError:
                    if e.errno == zmq.EAGAIN: 
                        pass
                
                    else:
                        self.logger.warning("zmq error whilst trying to recv a connect" +\
                            "request :"  + e.strerror)
                    
                except IndexError:
        
                    location = "CRClientServerManager.process_msgs"
                    log_string = """Oddly shaped packet received on 
                    cipr_sip_reqrouter socket: """
                
                    handle_generic_except(location=location, 
                                          log_string= log_string,
                                          logger=self.logger)
            
                except: 
                    location = "CRClientServerManager.process_msgs"
                    log_string = """unexpected error when processing msg
                     received on cipr_sip_reqrouter socket: """
                    handle_generic_except(location=location, 
                                          log_string=log_string,
                                          logger=self.logger)
                                          
                finally:
                    
                    self.client.setsockopt(zmq.LINGER, 0)
                    self.client.close()
                    self.pollserver.unregister(self.client)
                        
                    self.connector_inproc.setsockopt(zmq.LINGER, 0)
                    self.connector_inproc.close()
                    self.pollclient.unregister(self.connector_inproc)
                    
                
            
class ResponseTimer(threading.Thread):
    """ Run a count down timer that will set status of a machine to sync_fail if timedout
    """
    
    def __init__(self, machine):
        threading.Thread.__init__(self)
        
        
        self.machine = machine
        self.seconds = 5
        
        self.start() 
        
    def run(self):
        
        while not self.machine.status == utils.synced:
            
            if self.seconds == 0: 
                
                self.machine.status = utils.unresponsive
                break
            # in this case we might be able to manually re-sync, so we don't want
            # to disconnect this machine, we'll assume its still there since it 
            # reported a sync fail as opposed to not responding at all. 
            # This gives the user the chance to try a re-sync
            
            elif self.machine.status == utils.sync_failed:
                break
            else: 
                time.sleep(1.0)
                self.seconds -= 1
            
        

class CRServerMachine:
    """ Represents a render server
    """
    
    def get_status(self): return self.__status
    def set_status(self, value):
                   
        #check if the state is actually a valid one, situations where only 
        
        if not self.status in utils.states.keys():
            raise ValueError("attempted to set a state that is not valid")
        
        #we only update if the status has changed
        if value != self.__status:
        
            #There will be a lot of pain if we mess up status changes, putting a lock
            # here for safety's sake. A good example of why we need to do this is 
            # where we have time outs for status changes, like if the status doesnt
            # get updated from the remote machine in 5 secs, then change the status
            # to sync_fail. Get a machine that chimes in at the exact 5 second mark and
            # its anybody's guess what would happen.
            
            with self.lock:
            
                self.__status = value
                
                # if we've set up a time out for a task, and the node has 
                # responded, we need to cancel the timeout. We only do this if 
                # the status isn't unresponsive as in this case, the node has missed
                # a heartbeat and we've no idea what status its in. 
                
                if self.machine_uuid in self.client.machines_working and \
                    not value == utils.unresponsive:
                    
                    self.client.machines_working.pop(self.machine_uuid)
            
            if value ==utils.exited: 
                self.closed()
            
         
    
    status = property(fget = get_status, fset = set_status)
    
    def __init__(self, 
                    session_uuid,
                    client, 
                    node_name, 
                    cli_cip_router, 
                    cip_ssp_pubsub, 
                    ssp_cip_pubsub,  
                    ssp_endpoints,
                    machine_uuid = '', 
                    machine_cores = 0,
                    compute_devices=[],
                    k = 1.0,
                    t_s = 0.1):
                    
        self.session_uuid = session_uuid
        self.lock = threading.Lock()
        self.logger = client.logger
        self.__status = utils.ready
        self.last_render_time = 0.0
        self.last_draw_time = 0.0        
        self.node_name = node_name
        self.machine_uuid = machine_uuid
        self.screen_coords = ()
        self.node_A_manual = 0.001 # manual screen space allocation
        self.node_A_auto = 0.001 # automatic screen space allocation
        self.machine_cores = machine_cores
        self.eff_cores = float(machine_cores)
        self.cip_ssp_pubsub = cip_ssp_pubsub
        self.cli_cip_router = cli_cip_router
        self.ssp_cip_pubsub = ssp_cip_pubsub
        self.client = client
        self.exited = False
        self.ssp_endpoints = ssp_endpoints
        self.render_processes = list()
        if self.node_name == "local":
            self.render_thread_sock = self.client.render_thread_sock
        self.compute_devices = compute_devices
        self.enabled = True
        self.tile_x = 0
        self.tile_y = 0
        self.compute_device = 'CPU'
        self.k = k
        self.t_s = t_s
        
        ## LOAD LOCAL'S RENDER PERF DATA
        # if this is the local node, we'll need to load the data
        # for it now. 
        
        if machine_uuid == 'local':
            render_data = read_config_file([config.node_perf_data])
            
            local_render_data = render_data[config.node_perf_data]
        
            session_render_data = local_render_data.get(self.session_uuid.decode('utf-8'))
            
#             if session_render_data is not None:
#                 
#                 eng_data = session_render_data.get(engine)
#                 
#                 self.k = mean(session_render_data[0])
#                 self.t_s = session_render_data[1]
        
        
        
        
        
        if not self.ssp_cip_pubsub is None:
            self.client.poller.register(self.ssp_cip_pubsub, zmq.POLLIN)
        
        self.msg_map_to_function()
        
    
         
    def msg_map_to_function(self):
        
        self.msg_map = {
            utils.status_update:self.status_update,
            utils.render_stats:self.render_stats_fwd,
            utils.update_render_stats:self.update_render_stats,
            utils.get_nodes_by_uuid:self.fwd_node_rqst,
            utils.get_node_attrib_hashes:self.fwd_node_attrib_rqst,
            utils.finished_tile:self.get_finished_tile,
            utils.finished_view:self.get_finished_view,
            utils.progress_update:self.handle_transfer_prog_update,
            utils.render_failed:self.handle_failed_render,
            utils.cancel_tile_download:self.cancel_tile_download,
            utils.repair_item:self.fwd_repair_item_msg,
            utils.upload_task_complete:self.fwd_upload_task_complete,
            utils.upload_task_begin:self.fwd_upload_task_begin
            }
        
    def fwd_node_rqst(self, msg):
        
        self.cli_cip_router.send_multipart([msg.s_uuid, 
            bytes(json.dumps(msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])
        
    def fwd_node_attrib_rqst(self, msg):
        
        self.cli_cip_router.send_multipart([msg.s_uuid, 
            bytes(json.dumps(msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])
    
    def fwd_repair_item_msg(self, msg):
        """ Forwards a message from a render node regarding repair of the hash tree
        """
        
        self.cli_cip_router.send_multipart([msg.s_uuid, 
            bytes(json.dumps(msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])
        
    def fwd_upload_task_complete(self, msg):
        """ Forwards an update on and upload task
        """
        self.cli_cip_router.send_multipart([msg.s_uuid, 
            bytes(json.dumps(msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])
        
    def fwd_upload_task_begin(self, msg):
        """ Forwards message of an upload task that started
        """
        self.cli_cip_router.send_multipart([msg.s_uuid, 
            bytes(json.dumps(msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])
        
        
    def handle_transfer_prog_update(self, msg):
        """ Handle the reported file receive progress during uploads
        
        Arguments:
            msg: -  string  -   a json formatted string representing a MsgWrapper object
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
            Sends a msg to the client informing it of the % progress of file transfer
            
        Exceptions Raised:
            None.
            
        Description:
            This method is part of the feedback loop during file uploads that reports 
            the progress of the upload to a node on a 0-100% scale. 
                                
        """
        #we need to replace the node_uuid in this context since the receiving end 
        # will use the clients machine uuid which is wrong. 
        msg.attributes[utils.node_uuid] = self.machine_uuid
        msg.attributes[utils.node_name] = self.node_name
        
        self.cli_cip_router.send_multipart([msg.s_uuid, bytes(
            json.dumps(msg.serialize()),'utf-8') ])
            
    def cancel_tile_download(self, msg):
        """ Cleanup on cancelling an upload
        
        """
        
        self.status = utils.ready
        
    def render_stats_fwd(self, msg):
        #forward to the main process
        
        # calculate the task_uuid for these stats
        
        msg.attributes[utils.node_name] = self.node_name
        self.cli_cip_router.send_multipart(
            [msg.t_uuid, 
            bytes(json.dumps(
                msg.serialize(), 
                cls = utils.BTEncoder),'utf-8')])
                            
    
    def update_render_stats(self, msg):
        """ Get the latest render stats from a particular Node and update the relevant
        data. This is called once at the end of each render job.
                
        Arguments: MsgWrapper - Its expected that the MsgWrapper object contain:
            s_uuid = bytes - the identity of the peer that is associated with the 
                session that generated the status change.
            
        after a render job is complete each node will update the client_interface
        with new stats for k and t_s.        
        
        """
        self.k = msg.attributes[utils.k]
        self.t_s = msg.attributes[utils.t_s]
    
    def status_update(self, msg):
        
        status = msg.attributes[utils.status_update]
              
        self.client.logger.info("CRServerMachine.status_update" + l_sep +\
             'machine uuid :' + self.machine_uuid + \
                    ' has status : ' + utils.states[status])
        
        self.status = status
        
        self.update_client_status(msg)
        

        
    def update_client_status(self, msg):
        """ updates the user by sending client status to the main blender process
        
        Arguments: MsgWrapper - Its expected that the MsgWrapper object contain:
            s_uuid = bytes - the identity of the peer that is associated with the 
                session that generated the status change.
            
        On changes, each node will send its status change and that is handled here. The 
        stored values of the status, machine_uuid and node name are used.
        
        
        """
        msg.attributes[utils.active] = True
        msg.attributes[utils.node_uuid] = self.machine_uuid
        msg.attributes[utils.compute_devices] = self.compute_devices
        msg.attributes[utils.node_A_auto] = self.node_A_auto
        msg.attributes[utils.node_name] = self.node_name
        
        if not msg.message:
            msg.message = utils.status_update
        
        # a request for refresh of the status update will not contain
        # a valid status for this node in the msg, so add it
        if not utils.status_update in msg.attributes:
            msg.attributes[utils.status_update] = self.status
                                    
        self.cli_cip_router.send_multipart(
            [msg.s_uuid, bytes(json.dumps( msg.serialize(), 
                            cls = utils.BTEncoder), 'utf-8')]
                                        )
                                        
    
                            
    
    def handle_msgs(self, sockets):
    
        """ Handles a msg coming from the remote machine
        
        """
        
        
           
    
        #check to see if there are messages in the queue.
        if self.ssp_cip_pubsub in sockets:
            
            self.ssp_cip_pubsub_message = MsgWrapper.deserialize(
                                    self.ssp_cip_pubsub.recv_string())
            
            # TODO:JIRA:CR_66 need to be more consistent with use of command or message, 
            # should seriously consider using a single item to carry meta data 
            # on what handler should be used for a particular message.
            
            # unpack the msg and then call the handler                                                    
            if self.ssp_cip_pubsub_message.message in self.msg_map:
                
                func = self.msg_map[self.ssp_cip_pubsub_message.message]
                
                func(self.ssp_cip_pubsub_message)
            
            elif self.ssp_cip_pubsub_message.command in self.msg_map:
                
                func = self.msg_map[self.ssp_cip_pubsub_message.command]
                
                func(self.ssp_cip_pubsub_message)
                
        if self.machine_uuid == "local":
        
            if self.render_thread_sock in sockets:
                
                #the renderthread only sends stats, so we merely pass the msg
                # on, non need to decode it.
                #TODO: look at replacing code like this with a proxy since its likely
                # a proxy would be more efficient.
                msg = self.render_thread_sock.recv_string()
                
                message = MsgWrapper.deserialize(msg)
                
                if message.message == utils.finished_tile:
                    
                    self.get_finished_tile(message)
                    
                elif message.message == utils.finished_view:
                
                    self.get_finished_view(message)
                    
                else:
                    
                    message.attributes[utils.node_name] = 'local'
                    
                                     
                    self.client.cli_cip_router.send_multipart([message.t_uuid, 
                        bytes(json.dumps(message.serialize()), 'utf-8')])
                    
    
    def synchronise(self, msg):
        """ synchronise a connected machine with using contents of msg
        
        synchronise(self, msg)
        
        msg = MsgWrapper(command='', attributes = dict())
        
        This method causes the local machine's status to be set to synced immediately
        since by definition it is always synchronised. For a remote machine, the
        method sends the contents of msg to that machine.
        """
        
#         self.logger.info('sending data update ' + str(msg.attributes))
        
        if self.machine_uuid == 'local': self.status = utils.synced
        
        else:

            
            # self.status = utils.syncing  # wait until we actually hear that the 
            # node has responded and is syncing. 
            
            # the result of timing out will be that this machine is 
            # considered unreliable and will trigger the sync_fail condition. 
            
            self.start_time = time.perf_counter()
            self.time_elapsed = 0.0                           
            
            if self.machine_uuid in self.client.machines_working:
            
                pass
                
            else:           
            
                self.client.machines_working[self.machine_uuid] = self
                          
    def render(self, msg):
        """ Start or send a command to start a render.
        
        Arguments:
        
        t_uuid: bytes - the identity of the requesting peer. This is set by the 
            CrenderEngine class in crender_engine.py and is equal to the session_uuid, 
            suffixed with the frame number being rendered.
            
        msg: MsgWrapper - Should contain:
                attributes = {  
                    utils.current_frame:int,    - obvious
                    utils.screen_res:(int, int) - screen size x, y in pixels 
                    utils.render_engine:str,    - obvious
                    utils.img_output_fmt:str    - deprecated, soonish
                    utils.eng_samples:          - number of samples as given
                                                    by crender_engine.get_samples
                                
                             }
        
        
        """
    
        #Start a timer, we need to rule this guy out if we don't see its status change
        # or alternatively we could use a decorator on this function. Same could then
        # work for the sycn method, which I haven't written yet! haha :D
        
        
        if self.machine_uuid == 'local':
            
            self.status = utils.rendering
            
            scene_name = msg.attributes.get(utils.scene, "")
            
            update_msg = MsgWrapper(message = utils.render_stats, attributes = {
                utils.render_stats:[[0, "starting..."]], #list inside a list!
                utils.node_name:'local',
                utils.machine_uuid:'local',
                utils.state:self.status})
                
            self.cli_cip_router.send_multipart([msg.t_uuid, 
                                    bytes(json.dumps(update_msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])
            
            
            import os
        
            temp_blend_file = msg.attributes[utils.file_path]
            
                    
            # Allow screen resolution to be set here, doing the initialisation further 
            # up would leave us open to having to set some default value, not sure
            # what a wise value would be, this way we only create this variable
            # when it is actually needed.
            
            loc_node = msg.attributes[utils.nodes][self.machine_uuid]
            
            tile_x = loc_node[utils.tile_x]
            tile_y = loc_node[utils.tile_y]
            compute_device = loc_node[utils.compute_device]
            compute_devices = loc_node[utils.compute_devices]
            threads = loc_node[utils.process_threads]
            
            current_frame = msg.attributes[utils.current_frame]
            self.screen_resolution = msg.attributes[utils.screen_res]
            target_engine  = msg.attributes[utils.render_engine]
            samples = msg.attributes[utils.eng_samples]
            img_output_fmt = msg.attributes[utils.img_output_fmt] 
            exr_codec = msg.attributes[utils.exr_codec]   
            output_path = os.path.join(self.client.session_path, 
                                       msg.attributes[utils.scene],
                                       '_local_') 
            views = msg.attributes[utils.views]
            load_trusted = msg.attributes[utils.load_trusted]
            
            ## CREATE RENDER PROCESS
            
            process = create_render_process(
                load_trusted, self.screen_coords,
                tile_x, tile_y, compute_device, compute_devices,
                threads, temp_blend_file, output_path, target_engine, 
                img_output_fmt, current_frame, exr_codec,
                self.logger, scene_name)
            
            self.render_processes.append(process)
            
            
            render.CRRenderThread(
                msg.t_uuid, 
                self, 
                self.client, 
                process, 
                current_frame,
                self.screen_coords,
                self.screen_resolution,
                target_engine,
                samples,
                views = views
                )
            
        else:
        
            msg.attributes[utils.screen_coords] = self.screen_coords
            msg.attributes[utils.machine_uuid] = self.machine_uuid
                            
            msg.attributes[utils.message_uuid] = str(uuid.uuid4())
            
            self.cip_ssp_pubsub.send_string( json.dumps (msg.serialize(),
                                                    cls = utils.BTEncoder) )   
            
    def cancel_rendering(self, msg):  
        """ does what it says on the tin...
        """
        
        # if this is the local machine, just kill the process that is currently
        # rendering, or all of them if there's more than one. 
        if self.machine_uuid == 'local':
            
            
            self.status = utils.synced
            
            update_msg = MsgWrapper(message = utils.status_update,
                s_uuid = msg.s_uuid,
                attributes = {
                            utils.status_update:self.status
                                }
                                    )
            
            self.update_client_status(update_msg)
            
            
            for proc in self.render_processes:
                
                proc.kill()
                try:
                    stdout, stderr = proc.communicate(timeout = 1)
                except:
                    self.client.logger.error("CRServerMachine:cancel_rendering:" +\
                                         "timeout when trying to cancel render proc.")
                
            
            # self.status = utils.synced #TODO: CR-328 this should only be set 
            # by the render node, status should never be set by anything other than
            # by rcving a msg from that node. 
            self.render_processes.clear()
            
            
            
        
        # for remote nodes, send the cancel msg.
                
        else:
            
            self.cip_ssp_pubsub.send_string(json.dumps(msg.serialize(), 
                            cls = utils.BTEncoder))
    
    def handle_failed_render(self, msg):
        """ Handle the case where the render fails due to an error
        
        Arguments:
            msg - utils.MsgWrapper - message containing the error details, should contain:
                message - string - utils.render_failed
                t_uuid  - bytes  - unique id of the render task
                attributes - pydict - dictionary of attributes which should contain
                    {utils.error_message: string - contents of the error message}
        Returns:
            None
        Side Effects:
            Removes the affected node from the list of nodes that are actively rendering
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
        
        #need to reset the stats back to synced for the local machine
        if self.machine_uuid == 'local':
            self.status = utils.synced
        
        # the client server manager needs to remove this node from its list now and 
        # forward the message on to the user.
        self.client.render_failed(msg)
        
        
    def get_finished_view(self, msg):
        """ gets a finished view and communicates this to the client's session"""
        
            ## GET IMAGE FILE ATTRIBUTES 
        
        rend_node_img_path = msg.attributes[utils.image_file_path]
        
        #snd rqst to file requester for the img file
        server_router_id = self.machine_uuid
        fid = msg.attributes[utils.image_file_path]
        frame_no = msg.attributes[utils.current_frame]
        local_file_path = os.path.join( self.client.session_path,
                     os.path.split(fid)[1])
        rendered_view = msg.attributes[utils.view]
        
        ready_msg_attrs = {utils.screen_coords:self.screen_coords,
                            utils.current_frame:frame_no,
                            utils.node_name:self.node_name,
                            utils.file_path:(fid,local_file_path),
                            utils.node_uuid:self.machine_uuid,
                            utils.view:rendered_view}
        
        ## UPDATE K AND SETUP TIME
        self.k = msg.attributes[utils.k]
        self.t_s = msg.attributes[utils.t_s]
                            
        
        
        if self.machine_uuid == 'local':
            # if the local machine has rendered, we skip the file transfer, the
            # image result is already on the local drive anyway. Override the 
            # default location too.
            ready_msg_attrs[utils.file_path] = (fid, fid)
            
            ready_msg = MsgWrapper(command = utils.view_ready,
                t_uuid = msg.t_uuid,
                attributes = ready_msg_attrs)
                
            self.client.view_ready(ready_msg)
            
        
        else:
            
            ready_msg_attrs[utils.command] = utils.view_ready
            ready_msg_attrs[utils.cancelled_command] = utils.cancel_tile_download
            
            get_image_msg = MsgWrapper(command = utils.file_transf_req,
                                        t_uuid = msg.t_uuid,
                                        attributes = ready_msg_attrs
                            )
            
            self.client.file_request_sock.send_json(get_image_msg.serialize())
           
    
    def get_finished_tile(self, msg):
        """ Gets a finished tile to blender main process to be displayed
        """         
        
        ## GET IMAGE FILE ATTRIBUTES 
        
        rend_node_img_path = msg.attributes[utils.image_file_path]
        
        #snd rqst to file requester for the img file
        server_router_id = self.machine_uuid
        fid = msg.attributes[utils.image_file_path]
        frame_no = msg.attributes[utils.current_frame]
        local_file_path = os.path.join( self.client.session_path,
                     os.path.split(fid)[1])
        rendered_view = msg.attributes.get(utils.view,'')
        
        ready_msg_attrs = {utils.screen_coords:self.screen_coords,
                            utils.current_frame:frame_no,
                            utils.node_name:self.node_name,
                            utils.file_path:(fid,local_file_path),
                            utils.node_uuid:self.machine_uuid,
                            utils.view:rendered_view}
        
        ## UPDATE K AND SETUP TIME
        self.k = msg.attributes[utils.k]
        self.t_s = msg.attributes[utils.t_s]
                            
        self.logger.info("CRServerMachine.get_finished_tile; "+\
                         str(self.machine_uuid) + \
                         " finished a tile")
        
        if self.machine_uuid == 'local':
            # if the local machine has rendered, we skip the file transfer, the
            # image result is already on the local drive anyway. Override the 
            # default location too.
            ready_msg_attrs[utils.file_path] = (fid, fid)
            
            ready_msg = MsgWrapper(command = utils.result_ready,
                t_uuid = msg.t_uuid,
                attributes = ready_msg_attrs)
                
            self.client.result_ready(ready_msg)
            #for the local node we need to set the status back to synced 
            # manually
            self.status = utils.synced
            
            stat_msg = MsgWrapper(message = utils.status_update,
                s_uuid = self.session_uuid,
                attributes = {utils.status_update:self.status,
                            utils.active:True,
                            utils.node_uuid:'local'}
                )
            
            self.update_client_status(stat_msg)
            for proc in self.render_processes:
                stdout, stderr = proc.communicate()
            self.render_processes.clear()
            
            
        else:
            
            ready_msg_attrs[utils.command] = utils.result_ready
            ready_msg_attrs[utils.cancelled_command] = utils.cancel_tile_download
            
            get_image_msg = MsgWrapper(command = utils.file_transf_req,
                                        t_uuid = msg.t_uuid,
                                        attributes = ready_msg_attrs
                            )
            
            self.client.file_request_sock.send_json(get_image_msg.serialize())
        
        #TODO the request to get the file will likely trigger another handler
        # yet to be written that tells the engine in self.ready_engines that 
        # the file can now be loaded. Or why not just get the CRRenderThread
        # to send the message to get the file straight to the file requester and 
        # then have this handler called to tell the engine to load the file?
        
        
        
    def disconnect(self, msg):
        
        # if the node is still responding, we can send it a msg to shutdown
        # the node should respond with an exited status which will call this
        # instances closed method, finally removing the node from the session.
        
        if not self.status == utils.unresponsive:
        
            msg.attributes[utils.message_uuid] = str(uuid.uuid4())
        
            self.cip_ssp_pubsub.send_string( json.dumps (msg.serialize(),
                                                    cls = utils.BTEncoder) )
            self.closed()
                                                     
        # otherwise we'll have to close this instance down without waiting for 
        # a response.
        
        else:
            self.closed()
            
        
                                                    
    def closed(self):
        
        #nothing to disconnect if this is the local process
        if self.machine_uuid == 'local': pass
        
        else:
            #Disconnect the file server from the node
        
            disconnect_req_node_msg = MsgWrapper(command = utils.disconnect,
                    attributes = {utils.server_endpoint:
                        self.ssp_endpoints[utils.file_server_ep]})
                    
            disconnect_serv_node_msg = MsgWrapper(command = utils.disconnect,
                    attributes = {utils.server_endpoint:
                        self.ssp_endpoints[utils.file_requester_ep]})
                        
            self.client.file_server_sock.send_json(disconnect_serv_node_msg.serialize(), 
                                cls = utils.BTEncoder)
            self.client.file_request_sock.send_json(disconnect_req_node_msg.serialize(), 
                                cls = utils.BTEncoder)
    #         self.cip_ssp_pubsub.unbind()  
    
            # get ip address
            
            ssp_cip_ep = self.ssp_cip_pubsub.LAST_ENDPOINT.decode('utf-8')
            
            self.ssp_cip_pubsub.disconnect(ssp_cip_ep) 
                    #e.g. b'tcp://192.168.1.8:9003'
                    
            #disconnect the cip to ssp socket as well.. or there will be hell to pay
            proto, ip, port = ssp_cip_ep.split(":")
   
            cip_ssp_endpoint = "".join(
                [proto, ":", ip, ":", str(self.client.start_port + 3)])
            
            self.client.cip_ssp_pubsub.disconnect(cip_ssp_endpoint)
                
        
            self.client.poller.unregister(self.ssp_cip_pubsub)
    
        
            self.ssp_cip_pubsub.close()

        #remove ourselves from the list of active machines since we're now gone!
        self.exited = True
        

class CRClientServerManager:
    """ Client Server Manager
    """
    
    client_key_pub = ''
    client_key_secret = ''
    
    def set_rqst_cloud_insts(self, value):
        
        if isinstance(value, bool):
        
            self.__request_cloud_instances = value
            self.logger.info("CRClientServerManager.set_rqst_cloud_insts" + l_sep+\
                "Set request_cloud_insts to" + str(self.__request_cloud_instances))            
        else: 
            raise TypeError("Expected the input for this property to be a boolean but " +\
                "got a " + str(type(value)) + " instead.")
    
    def get_rqst_cloud_insts(self):
    
        return self.__request_cloud_instances
    
    
    request_cloud_insts = property(fget = get_rqst_cloud_insts, 
            fset = set_rqst_cloud_insts)
    
    
    def __init__(self):
        
        self.__request_cloud_instances = False
        self.__status = utils.null
        
        self.cr_path = utils.get_cr_path()
        self.machine_uuid = utils.get_machine_uuid()
            
        self.connections = {}
        self.polled_connections = {}
        self.machines = {}
        self.rendering = {}
        self.machines_working = {}
        self.syncing = {}
        self.machine_uuid = utils.get_machine_uuid()
        self.pending_connections = {}
        self.ready_engines = {}
        self.progress_tiles = {}
        self.http_requests = {}
        self.http_refresh_interval = 30.0
        #note this is actually reset each time init_session is called to dump 
        # any pending render requests from the old session that may still 
        # be hanging around.
        self.render_jobs_queue = queue.Queue()
        
        ## SETUP SIGNAL HANDLERS/EXIT HANDLERS
        signal.signal(signal.SIGTERM, self.handle_signal)
        atexit.register(self.shutdown)
        
        
        
            
        # synchroniser = CRSyncrhoniser()
#         self.slaves
        self.logger = logger 
        
        
        self.setup_network()
        
        
        
        
  
        #TODO:JIRA:CR-66 Fix up the messaging, lots of stuff we are doing
        # doesn't make sense. Here we use 'message' rather than 'command'.
        # As far as the code is concerned, we should be consistent in the
        # way we are wrapping our messages, i.e. either use command or 
        # message. using a mix might be good for readability but not great
        # for maintaining or debugging.
        
         
        
        self.map_msg_to_function()
        
        
        self.keep_alive = True
#         self.target_engine = "BLENDER_RENDER"
        
        self.cs_manager_main()
        
    def handle_hello(self, sess_uuid ,msg):
        """ Respond to a hello msg from blender main, used when establishing connections
        """

        response_msg = MsgWrapper(message = utils.hello_cip, 
                                        t_uuid = msg.t_uuid,
                            attributes = {utils.machine_uuid:self.machine_uuid})
                    
        self.cli_cip_router.send_multipart([sess_uuid,
                                    bytes(json.dumps(response_msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])

        self.logger.debug("CRClientServerManager.handle_hello" + l_sep +\
            " responding to hello request..")
    
    #######################################################################
    #The following definitions will aid understanding of the conn names 
    #  cli  - Client Process (ie Blender Main Process)
    #  cip  - Client Interface Process (ie this process)
    #  sip  - Server Interface Process (on the remote machine)
    #  ssp  - Server Session Process (on the remote machine)
    
    #######################################################################    
    
    
        
        
    
        
    def setup_network(self):
        #
        # Define the sockets required to communicate with client        
        self.context = zmq.Context()   
        
        #Set up Authentication options
        auth = ThreadAuthenticator(self.context)
        auth.start()        
        # Tell the authenticator how to handle CURVE requests
        auth.configure_curve(domain='*', location=zmq.auth.CURVE_ALLOW_ANY)
        
        #Create the certificates
        conf_path = os.path.normpath(os.path.expanduser("~/cr/.conf"))
        cert_path = os.path.join(conf_path, '.certificates/client')
        if os.path.exists(cert_path):
            shutil.rmtree(cert_path)
        os.makedirs(cert_path)
                
        client_pub_file, client_secret_file = \
            zmq.auth.create_certificates(cert_path, "client")
        
        self.client_key_pub, self.client_key_secret = \
            zmq.auth.load_certificate(client_secret_file) 
        
        #Need to do error checking CR-88, any call to a zmq function should have a 
        # way to check for errors or, umm, not success? 
        user_preferences = bpy.context.preferences
        addon_prefs = user_preferences.addons[crowdrender.package_name].preferences
        
        self.start_port = addon_prefs.start_port
        self.port_range = addon_prefs.port_range
        self.network_timeout = float(addon_prefs.network_timeout)
        
        
        self.cli_cip_router = self.context.socket(zmq.ROUTER)
        self.cli_cip_router.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.cli_cip_router.bind("tcp://127.0.0.1:" + str(self.start_port + 1))
        self.connections['cli_cip_router'] = self.cli_cip_router
        
        self.file_serv_sub = self.context.socket(zmq.SUB)
        self.file_serv_sub.set(zmq.SUBSCRIBE, b'')
        # self.file_serv_sub connects once the file server is active 
        self.connections['file_serv_sub'] = self.file_serv_sub                  
        
         
        self.connector_inproc = self.context.socket(zmq.DEALER)
        self.connector_inproc.bind("inproc://connector")
        self.connections['sender'] = self.connector_inproc
        
  
        # Connection for PUB_SUB : Client_Interface_Process to Server_Session_Process (Local)
        self.cip_ssp_pubsub = self.context.socket(zmq.PUB)
        self.cip_ssp_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1) #9003
        self.cip_ssp_pubsub.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 20)        
        #self.cip_ssp_pubsub.bind("tcp://127.0.0.1:9003") 
        
        self.connections['cip_ssp_pubsub'] = self.cip_ssp_pubsub                        
        
        self.file_server_addr = 'file_server'
        self.file_server_sock = self.context.socket(zmq.PAIR)
        self.file_server_sock.bind("inproc://" + self.file_server_addr)
        self.connections['file_server'] = self.file_server_sock
       
        self.render_thread_sock_addr = 'render_thread'
        self.render_thread_sock = self.context.socket(zmq.SUB)
        self.render_thread_sock.subscribe(b'')
        self.render_thread_sock.bind("inproc://" + self.render_thread_sock_addr)
        self.connections['render_thread'] = self.render_thread_sock
        

        self.http_request_sock_addr = 'http_request'
        self.http_request_sock = self.context.socket(zmq.DEALER)
        self.http_request_sock.bind('inproc://http_request')
        self.connections['http_request'] = self.http_request_sock



        self.file_request_sock_addr = 'file_request'
        self.file_request_sock = self.context.socket(zmq.PAIR)
        self.file_request_sock.bind("inproc://" + self.file_request_sock_addr)
        self.connections['file_request'] = self.file_request_sock
        
        # Initialize poll set for the receiving ports only
        self.poller = zmq.Poller()
        
        self.poller.register(self.cli_cip_router  , zmq.POLLIN)
        self.poller.register(self.connector_inproc, zmq.POLLIN)
        self.poller.register(self.render_thread_sock, zmq.POLLIN)
        self.poller.register(self.http_request_sock, zmq.POLLIN)
        self.poller.register(self.file_server_sock, zmq.POLLIN)
        self.poller.register(self.file_serv_sub, zmq.POLLIN)
        self.poller.register(self.file_request_sock, zmq.POLLIN)
        
        self.polled_connections['sender'] = self.connections['sender']
        self.polled_connections['cli_cip_router'] = self.connections['cli_cip_router']
        self.polled_connections['render_thread'] = self.connections['render_thread']
        self.polled_connections['file_serv_sub'] = self.connections['file_serv_sub']
        self.polled_connections['file_request'] = self.connections['file_request']
        self.polled_connections['file_server'] = self.connections['file_server']
        self.polled_connections['http_request'] = self.connections['http_request']
        
        self.logger.info("CRClientServerManager.setup_network" +l_sep+\
             "Network Interfaces Initialised")

    
    def process_msgs(self):
        #sometimes this is put in a 'try/except handler'
        # 1000 is equivilent to a 1 second timeout
        sock_events = dict(self.poller.poll(16))
        #self.logger.info("process_msgs : completed timeout")
        
        try:
        #for now, retain a message data block for each interface
            if self.cli_cip_router in sock_events:
                
                sess_uuid, raw_string = self.cli_cip_router.recv_multipart()
                
                
                
                cli_cip_router_message = MsgWrapper.deserialize(
                                raw_string.decode('utf-8'))
                                
                                
                
    
                #now process the message
                self.logger.debug("CRClientServerManager.process_msgs: " + l_sep +\
                    " " + cli_cip_router_message.message + ' ' +\
                         cli_cip_router_message.command)
                
                
    
                if cli_cip_router_message.command in self.msg_map:
                    
                    func = self.msg_map[cli_cip_router_message.command]
                
                    func(sess_uuid, cli_cip_router_message)
            
                elif cli_cip_router_message.message in self.msg_map:
                    
                    func = self.msg_map[cli_cip_router_message.message]
                
                    func(sess_uuid, cli_cip_router_message)
            
    
            if self.connector_inproc in sock_events:
                
                msg_raw = self.connector_inproc.recv_string()
                
                msg = MsgWrapper.deserialize(
                                msg_raw
                                )
                
                
                if msg.message in self.msg_map:
                
                    func = self.msg_map[msg.message]
                    
                    func(msg)
                
                else:
                    
                    self.logger.warning("CRClientServerManager.process_msgs" + l_sep +\
                        " received msg that didn't have a valid 'message' field: " +\
                                        str(msg.message))
    
                
            if self.http_request_sock in sock_events:
                
                msg_raw = self.http_request_sock.recv_string()
                
                msg = utils.MsgWrapper.deserialize(
                                msg_raw)
                
                
                if msg.message in self.msg_map:
                
                    func = self.msg_map[msg.message]
                    
                    func(msg)
                    
                else:
                    
                    self.logger.warning("received msg that didn't have a valid 'message' "+\
                            "field: " +  str(msg.message))
    
    
    
            if self.file_request_sock in sock_events:
            
                msg_raw = self.file_request_sock.recv_string()
                
                msg = MsgWrapper.deserialize(
                                msg_raw)
                
                if msg.command in self.msg_map:
                    func = self.msg_map[msg.command]
                    
                    func(msg)
                
                elif msg.message in self.msg_map:
                
                    func = self.msg_map[msg.message]
                    
                    func(msg)
                
                else:
                    self.logger.warning("CRClientServerManager.process_msgs" + l_sep +\
                        " received msg that didn't have a valid "+\
                        "'message' or 'command' field: " +\
                        str(msg.message) + " " + str(msg.command))
                                        
            if self.file_server_sock in sock_events:
                
                msg_raw = self.file_server_sock.recv_string()
                
                msg = MsgWrapper.deserialize(
                                msg_raw)
                
                if msg.command in self.msg_map:
                    func = self.msg_map[msg.command]
                    
                    func(msg)
                
                elif msg.message in self.msg_map:
                
                    func = self.msg_map[msg.message]
                    
                    func(msg)
                
                else:
                    self.logger.warning("CRClientServerManager.process_msgs" + l_sep +\
                        " received msg that didn't have a valid 'message' or"+\
                        " 'command' field" +\
                                        str(msg.message) + " " + str(msg.command))
                
            
            if self.file_serv_sub in sock_events:
                """ Simple forwarding method for progress updates coming from the file server
                """
                
                json_msg = self.file_serv_sub.recv_string()
                
                msg = MsgWrapper.deserialize(json_msg)
                
                self.cli_cip_router.send_multipart([
                                msg.s_uuid,
                                bytes(json_msg, 'utf-8')
                                ])
            
            #for each machine, handle any messages we just got      
            for machine in self.machines.values():
                
                machine.handle_msgs(sock_events)
            
        except zmq.ZMQError as e:
                
                if e.errno == zmq.EAGAIN: 
                    pass
                
                else:
                    self.logger.warning("zmq error whilst trying to recv a connect" +\
                        "request :"  + e.strerror)
                    
        except IndexError:
        
            location = "CRClientServerManager.process_msgs"
            log_string = """Oddly shaped packet received on 
            cipr_sip_reqrouter socket: """
                
            handle_generic_except(location=location, 
                                  log_string= log_string,
                                  logger=self.logger)
            
        except: 
            location = "CRClientServerManager.process_msgs"
            log_string = """unexpected error when processing msg
             received on cipr_sip_reqrouter socket: """
            handle_generic_except(location=location, 
                                  log_string=log_string,
                                  logger=self.logger)    
    
                                
             
    def cs_manager_main(self):
        """ Main entry point for the CR Client Interface Process
        
        
        """       
        
        
        
        while(self.keep_alive):
            
            
            
            self.process_msgs()
            
            
            # check to see if there are any machines that have not responded yet to the
            # client's request for sync, render etc. Mark them as unresponsive if they
            # are late. They will be added back if they eventually respond, but they
            # won't be included in the render unless they respond.
            
            for machine in self.machines_working.values():
                
                machine.time_elapsed = time.perf_counter() - machine.start_time
                
                if machine.time_elapsed > TIMEOUT and \
                         not machine.status == utils.unresponsive: 
                    
                    machine.status = utils.unresponsive
  
            
            if not self.render_jobs_queue.empty():
            
                job = self.render_jobs_queue.get_nowait()
                
                self.do_render_job(job)
                
                self.render_jobs_queue.task_done()
            
           
            for machine in list(self.machines):
                if self.machines[machine].exited:
                    self.machines.pop(machine)
                    
                        
    def update_tile_size(self, sess_uuid, msg):
        """ Updates node settings for a connected machine.
        
        Arguments: 
            sess_uuid:      String      - String containing a unique id to 
                                ensure we're updating the correct session.
            msg:            MsgWrapper  - crowdrender message wrapper object. 
                                Must have attributes ={
                                    utils.node_name:string
                                    utils.tile_x:int
                                    utils.tile_y:int
                                    utils.compute_device:string
                                    utils.compute_devices:list[dictionaries{}]
                                }
            Returns:
                None
            
            Side Effects:
                Sets new values for relevant attributes of machine       
        
        """
        for mach in self.machines.values():
            if mach.node_name == msg.attributes[utils.node_name]:
                #You've found the right machine. Good Job.
                # msg.attributes[utils.machine_uuid] = mach.machine_uuid
                
                # self.cip_ssp_pubsub.send_string( json.dumps (msg.serialize(),
                                                # cls = utils.BTEncoder) )
                mach.tile_x = msg.attributes[utils.tile_x]
                mach.tile_y = msg.attributes[utils.tile_y]
                mach.compute_device = msg.attributes[utils.compute_device]
                mach.compute_devices = msg.attributes[utils.compute_devices]    
              
    def update_node_status(self, s_uuid, msg):
        """ Return the status for each render node
        
        Arguments:
            msg:        utils.MsgWrapper - CR message object which must contain.
            s_uuid:     string -    unique id of the requesting peer session   
        Returns:
            nothing
        Side Effects:   
            gets each node to report its status to the requesting host 
            
        Exceptions
            None:
        
        Description:
            This method is used to update the visible node status. It is used
            when a file load is done since at that point, nodes that were saved
            in the file will have been loaded, potentially with old status 
            values that need to be cleared.
            
        """ 
        import copy
        
        msg.s_uuid = s_uuid
        
        
        
        for m_uuid, mach in self.machines.items():
            mach.update_client_status(copy.deepcopy(msg))                       
       
    
    def data_update(self, s_uuid, msg):
        """ forward data updates to all servers
        
        """
        
        
        self.top_hash = msg.attributes[utils.top_hash]
        
        for mach_uuid, machine in self.machines.items():
            
            msg.attributes[utils.machine_uuid] = mach_uuid
            machine.synchronise(msg) 
           #  machine.status = utils.syncing
#             self.syncing[uuid] = machine
        msg.attributes[utils.message_uuid] = str(uuid.uuid4())
        
        self.cip_ssp_pubsub.send_string( json.dumps (msg.serialize(),
                                                cls = utils.BTEncoder) )
            
        
        #Note we should be using objects that represent servers here, but
        # in the prototype version we are only connecting two machines
        
        
        
#     def update_target_engine(self, msg):
#         """ Change the render engine on all nodes according to input
#         
#         
#         """
#         
#         #Set the render engine
#         self.target_engine = msg.attributes[utils.render_engine]
#         
#         self.logger.debug("CRClientServerManager.update_target_engine" +\
#              l_sep +\
#              " enginer used: " + self.target_engine)
#         
#         # forward the message onto to the other nodes
#         
#         msg.attributes[utils.message_uuid] = str(uuid.uuid4())
#         
#         self.cip_ssp_pubsub.send_string(json.dumps(msg.serialize(), 
#                             cls = utils.BTEncoder))
                                                        
    def render(self, t_uuid, msg):
        """ Forward a command to render to all servers
        
        """
        msg.t_uuid = t_uuid
        
        self.render_jobs_queue.put(msg)
        
    def do_render_job(self, msg):    
       #indices for screen coordinates 
        X = 0
        Y = 1
        PERCENTAGE = 2
        
        screen_resolutions = msg.attributes[utils.screen_res]
        
        screen_res_x = screen_resolutions[X] * screen_resolutions[PERCENTAGE] / 100
        screen_res_y = screen_resolutions[Y] * screen_resolutions[PERCENTAGE] / 100
        samples = msg.attributes[utils.eng_samples]
        nodes = {uuid:m for uuid ,m in self.machines.items() \
            if uuid in msg.attributes[utils.nodes]}
        
        ### SELECT WHICH NODES CAN RENDER ###   
        
        machines_rendering = {}
        
        # create a list of all nodes
        for uuid, machine in nodes.items():
            
            #obviously we skip the machines that are not able to contribute due 
            # to errors
            
            #setting the manual load balancing value.
            manual_lb = msg.attributes[utils.node_A_manual_values].get(uuid, 0.0)
            
            machine.node_A_manual = manual_lb
            
            if not machine.status == utils.synced: continue
            machines_rendering[uuid] = machine
            
        #If there are no machines enabled for rendering Don't try and render.
        if not machines_rendering:
            report_msg = MsgWrapper(command = utils.ext_report,
                                    attributes = {
                                    utils.message_type:'WARNING',
                                    utils.message:"No machines enabled"
                                    })
            
            self.cli_cip_router.send_multipart([msg.t_uuid, 
                bytes(json.dumps(report_msg.serialize(), 
                                cls = utils.BTEncoder), 'utf-8')])
        else:
            
            ### CALCULATE TILE SIZES FOR EACH NODE ###    
            machines_rendering = render.screen_divide(machines_rendering, 
                        screen_res_x, 
                        screen_res_y,
                        samples,
                        msg.attributes[utils.manual_loadb],#use manual load balancing
                        self.logger)
            
            
            self.progress_tiles = machines_rendering
                    
            
            ### SEND THE RENDER COMMAND ###
            
            #sort the machines, done so that 'local' will be last since the call to 
            # render on local will block until the render is finished. Effictively this would
            # make all other machines wait until its finished before they can render.
                
            sorted_macs = sorted(machines_rendering)
                
            for uuid in sorted_macs:
                
                machine = machines_rendering[uuid]
                
                machine.render(msg)
                
                self.rendering[machine.machine_uuid] = machine
        
        
    def cancel_render(self, sess_uuid, msg):
        """ stop all render tasks
        """
        
        # send cancel msg to all ndoes
        for uuid, machine in self.machines.items():
            machine.cancel_rendering(msg)

        self.rendering.clear()
        self.progress_tiles.clear()
        
        self.logger.info("CRServerManager.cancel_render: " + "Cancelling render")
 
        
    def render_engine_ready(self, uuid, msg):
        """ Handle event where render engine signals ready to recv frames
        """
        
        #add an entry into the ready_engines list
        self.ready_engines[uuid] = msg.attributes[utils.current_frame]
        
    def render_failed(self, msg):
        """ Handle the case where the render fails due to an error
        
        Arguments:
            msg - utils.MsgWrapper - message containing the error details, should contain:
                message - string - utils.render_failed
                t_uuid  - bytes  - unique id of the render task
                attributes - pydict - dictionary of attributes which should contain
                    {utils.error_message: string - contents of the error message}
        Returns:
            None
        Side Effects:
            Removes the affected node from the list of nodes that are actively rendering
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
        node_uuid = msg.attributes[utils.node_uuid]
        node_name = msg.attributes[utils.node_name]
        try:
            #Remove the node from the list of rendering machines
            self.progress_tiles.pop(node_uuid)

        except KeyError:
            
            self.logger.error("CRServerManager.render_failed " +\
                "KeyError was encountered when trying to remove "+\
                str(node_name) + " from the list of rendering nodes")
        
        self.logger.warning("CRServerManager.render_failed" + l_sep +\
            " Render failed on :" + self.machines[node_uuid].node_name +\
            " the error messsage follows: " +\
                 l_sep.join(msg.attributes[utils.error_message])
            )
        
        self.cli_cip_router.send_multipart([msg.t_uuid, 
            bytes(json.dumps(msg.serialize()),'utf-8')])
        
    def view_ready(self, msg):
        """ Handle event where a view has been received, tells the render engine to redraw 
        
        A view is a render tile that belongs to a stereoscopic render. We simply tell blender
        to load the view and keep going, we only need to finish once all views are complete.
        
        """    
           
        
        # Route the message to the right render engine instance inside blender
        self.cli_cip_router.send_multipart([msg.t_uuid, 
            bytes(json.dumps(msg.serialize()),'utf-8')])
           
 
        
        
    def result_ready(self, msg):
        """ Handle event where a tile has been received, tells the render engine to redraw 
        
        This method will check the self.progress_tiles collection for the tile that
        is identified in the msg argument (currently by node_uuid as each node only 
        gets one tile at the moment). If the tile is found in the collection, then 
        a msg is sent to the current active render engine in blender's main process 
        telling it to redraw the results from the file who's path is given in the msg.
        
        Once all tiles are removed from the list, a final msg is sent to the 
        render engine in blender to finish the frame. See CrenderEngine.frame_done for 
        the details.
        
        """    
           
        
        # Route the message to the right render engine instance inside blender
        self.cli_cip_router.send_multipart([msg.t_uuid, 
            bytes(json.dumps(msg.serialize()),'utf-8')])
           
        node_uuid = msg.attributes[utils.node_uuid]
        
        if node_uuid in self.progress_tiles:
            self.progress_tiles.pop(node_uuid)
        else:
            self.logger.warning("CRClientServerManager.result_ready()" + l_sep +\
            "Node " + str(node_uuid) + " not found in progress_tiles")
        
        if not self.progress_tiles:
            #when progress_tiles is empty we need to finalise the render
            final_msg = MsgWrapper(command = utils.finalise_render)
            
            self.cli_cip_router.send_multipart([msg.t_uuid, 
                bytes(json.dumps(final_msg.serialize()),'utf-8')])
        
         
        
    def contact_server(self, sess_uuid, msg):
        
        """
        Contact a server and ask for a connection
        
        Method starts an instance of the CRContactServer thread which actually does the 
        connect to the remote server. The thread attempts to connect and then signals
        via a msg that the server is either ready to connect, or that the connection 
        failed.
        
        """
        
       
        
        #ensure we update the temp file path. Since this is used for transferring the 
        # file to other nodes
        upload_task = msg.attributes[utils.upload_task]
        
        for node_name, node_data in msg.attributes[utils.render_nodes].items():
            
            try:
            #'server_int_proc' is used as the default for when we're connecting
            # to a LAN based node. Its replaced by a random uuid when connecting 
            # to a cloud based node.
                access_key = node_data.get(utils.node_access_key, '')
                node_address = node_data.get(utils.node_address, '')
                node_uuid = node_data.get(utils.node_uuid, '')
                
                
                node = self.machines.get(node_uuid)
                 
                if node is not None:
                # if the node is already connected, we should disconnect it, then 
                # reconnect it. 
                    node.closed()
#                     disconnect_msg = utils.MsgWrapper(
#                      
#                         command = utils.disconnect,
#                             attributes = {
#                                    utils.machine_uuid:node_uuid
#                                         }
#                             )
#                     node.disconnect(disconnect_msg)
                    
                    
                
                ipaddress.ip_address(node_address)
                
                new_conn = dict({utils.node_name:node_name,
                            utils.node_address:node_address,
                            utils.access_key:access_key,
                            utils.upload_task:upload_task})
                
                if node_address == "0.0.0.0":
                    #0.0.0.0 is a special address so don't use it
                    fail_msg =MsgWrapper(
                        message = utils.connect_failed,
                        s_uuid = sess_uuid,
                        attributes = {
                            utils.node_address:node_address,
                            utils.node_name:node_name}
                        )
                    
                    self.server_no_connect(fail_msg)
                    
                elif not node_address in self.pending_connections:
                
                    self.pending_connections[node_address] = new_conn
                    
                    self.logger.info("CRClientServerManager.contact_server" +\
                        l_sep +\
                        ' Attempting to connect to a new server at ' + \
                        'tcp://'+ node_address + ':' + str(self.start_port + 6)) 
                                
                    
                    #try to connect, obviously...
                    CRContactServer(self, new_conn, sess_uuid)
                    
                else:
                    
                    self.logger.info("CRClientServerManager.contact_server" +\
                        l_sep +\
                        ' Duplicate connection request for : ' + \
                        'tcp://'+ node_address + ':' +\
                        str(self.start_port + 6) +\
                        " going to ignore this one.") 
                
                
                
            except ValueError:
                
                #TODO: the default value, unless saved to blend file, 
                # will always cause this error since its not an ip address
                # its just a string that says '[default]'
                # Need to come up with another method. At start up we want to 
                # connect to the last known ip addresses of servers we were 
                # using. We should be able to load the addresses at load time
                # and init_remote_sockets could then re-establish connections.
                self.logger.error("CRClientServerManager.contact_server" +\
                        l_sep +\
                        " invalid server address on init")
                
                
                fail_msg =MsgWrapper(
                    message = utils.connect_failed,
                    s_uuid = sess_uuid,
                    attributes = {
                        utils.node_address:node_address,
                        utils.node_name:node_name}
                    )
                
                self.server_no_connect(fail_msg)

    
    def try_again(self, sess_uuid, msg):
    
        node_name = msg.attributes[utils.node_name]
        
        trying_again_msg = MsgWrapper(
            message = utils.progress_update,
            s_uuid = sess_uuid,
            attributes = {
                utils.node_name:node_name,
                utils.state:utils.retrying_connect,
                utils.message:"Request timed out, trying again...."}
                )
        
        self.cli_cip_router.send_multipart([sess_uuid,
            bytes(json.dumps(trying_again_msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])                        
    
    
    def server_no_connect(self, msg):
        """ Handles the event when a connection cannot be made
        
        Connections can fail in a number of ways, either the server does not respond 
        at all to the request to conenct, or there may be a failure to establish 
        a file requester/file server session which effectively results in a failed
        connection as there can be no data transfer between the master and client nodes.
        
        Arguments: 
        
        msg: MsgWrapper - must contain 
            s_uuid: string - required to be able to rout the fail msg back to the client
            attributes = {
            node_name: string
            node_address: string - helps id the node in the interfaces
                        }
            
        """ 
        
        node_name = msg.attributes[utils.node_name]
        node_address = msg.attributes[utils.node_address]        
        
        if node_address in self.pending_connections:
            self.pending_connections.pop(node_address)
        
        connect_failed_msg = utils.MsgWrapper(
            message = utils.connect_failed,
            attributes = {
                utils.node_name:node_name,
                utils.node_address:msg.attributes[utils.node_address],
                utils.status_update:utils.connect_failed}
                        )
        
        self.cli_cip_router.send_multipart([msg.s_uuid, 
            bytes(json.dumps(connect_failed_msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])
    
    def server_connect(self, msg):
        """ Handles the event of a server responding to connect request
        
        Arguments
        msg: MsgWrapper - must contain
            s_uuid: string - session uuid for the request, required for routing
            attributes = {
                machine_uuid: string - a unique id for the requesting machine
                machine_cores: int - how many CPU cores the machine has
                server_endpoint: string - the ip address and port to bind to
                compute_devices: A list of the machines compute devices
                            }
                            
        returns: nothing
        
        Description
        This method handles the event where a node replies back that is is ready to 
        do a handshake. The handshake at the moment consists of;
            
            1. A file server to serve the users files to the node
            2. A file requester to request results of tasks from the node
            3. sockets for command and control of the node
            4. Sending an intialisation msg to make the node check its version of the
                users files (if it has any) and request upload of files if the 
                node calculates it is out of sync with the requesting client.
            
                    
        """
        
        
        #Get pending request and start to finalise it
        new_conn = self.pending_connections.pop(
            msg.attributes[utils.node_address])
        
        self.logger.info("CRClientServerManager.server_connect" +\
                    l_sep +\
                    "finalising new connection to :" + str(new_conn))
        node_address = new_conn[utils.node_address]
        node_name = new_conn[utils.node_name]
        upload_task = new_conn[utils.upload_task]
        
        sess_uuid = msg.s_uuid
        
        remote_machine_uuid = msg.attributes[utils.machine_uuid]
        remote_machine_cores = msg.attributes[utils.machine_cores]
        file_server_endpoints = msg.attributes[utils.server_endpoint]
        
        #_______ MAP ENDPOINTS FOR FILE SERVER/REQUESTER CORRECTLY ______________________#
        
        
        # server nodes can have multiple active network interfaces which they 
        # will bind to. We need to only connect to the address we have contacted
        # them on, plus the port number that the server has bound to for the
        # corresponding interface.
            
        ssp_fs_endpoints = [
            ("tcp://" + node_address + ":" + str(endpoint[1]), 
            msg.public_key.decode('utf-8')) \
            for endpoint in file_server_endpoints[utils.file_server_ep] \
            if endpoint[0] == node_address 
            ] 
        
        if len(ssp_fs_endpoints) < 1: 
            ssp_fs_endpoints.append(("tcp://" + node_address +\
                ":" + str(file_server_endpoints[utils.file_server_ep][0][1]),
                msg.public_key.decode('utf-8')))
                
        ssp_fr_endpoints = [
            ("tcp://" + node_address + ":" + str(endpoint[1]),
            msg.public_key.decode('utf-8')) \
            for endpoint in file_server_endpoints[utils.file_requester_ep] \
            if endpoint[0] == node_address 
                          ] 
        
        if len(ssp_fr_endpoints) < 1: 
            ssp_fr_endpoints.append(("tcp://" + node_address +\
                ":" + str(file_server_endpoints[utils.file_requester_ep][0][1]),
                msg.public_key.decode('utf-8')))            
            
            
        #_______CONNECT FILE SERVER _____________________________________________________#
        
        #Connect the file server to the new node
        connect_node_msg = utils.MsgWrapper(command = utils.connect_node,
                        s_uuid = msg.s_uuid,
                        attributes = {utils.server_endpoint:ssp_fr_endpoints,
                                    utils.requesting_id:remote_machine_uuid,
                                    utils.node_name:node_name})
                        
        self.file_server_sock.send_json(connect_node_msg.serialize(), 
                            cls = utils.BTEncoder)
                            
        #_______CONNECT FILE REQUESTER __________________________________________________#
        
        connect_node_msg = utils.MsgWrapper(command = utils.connect_node,
                        s_uuid = msg.s_uuid,
                        attributes = {
                                    utils.server_endpoint:ssp_fs_endpoints,
                                    utils.requesting_id:remote_machine_uuid,
                                    utils.node_name:node_name})
                        
        self.file_request_sock.send_json(connect_node_msg.serialize(), 
                            cls = utils.BTEncoder)
        
        
        #_______SOCKET SETUP_____________________________________________________________#
        
        # Connection for PUB_SUB : Server_Session_Process (Local) to Client_Interface_Process
        ssp_cip_pubsub = self.context.socket(zmq.SUB)
        ssp_cip_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        ssp_cip_pubsub.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 20)
        # self.ssp_cip_pubsub.connect("tcp://127.0.0.1:9051")        
        ssp_cip_pubsub.setsockopt(zmq.SUBSCRIBE,b'')   #for the moment subscribe to everything
        
        self.cip_ssp_pubsub.curve_secretkey = self.client_key_secret
        self.cip_ssp_pubsub.curve_publickey = self.client_key_pub
        self.cip_ssp_pubsub.curve_serverkey = msg.public_key
        
        ssp_cip_pubsub.curve_secretkey = self.client_key_secret
        ssp_cip_pubsub.curve_publickey = self.client_key_pub
        ssp_cip_pubsub.curve_serverkey = msg.public_key
        
        try:

            ssp_cip_pubsub.connect("tcp://" + node_address +\
                                   ":" +  str(self.start_port + 10)) # old port ":9051") 
            
            
            self.cip_ssp_pubsub.connect("tcp://" + node_address +\
                                     ":" + str(self.start_port + 3)) # old port ":9003")
                                     
           
            
        except zmq.ZMQError as e: 
        
            # connecting does have some  errors we can handle, but thy are all pretty 
            # terminal. So its probably easier to just log the error and raise. 
            self.logger.info("CRClientServerManager.server_connect" +\
                    l_sep +\
                    "SHIT! zmq error, :" + e.strerror)
            
            #re raise the last exception, which is what raise does with no expressions 
            # after it
            raise
            
        # if we managed to get here, its all good and we are connected! :D    

        
        self.machines[remote_machine_uuid] = \
            CRServerMachine(
                sess_uuid,
                self, 
                node_name,
                self.cli_cip_router, 
                self.cip_ssp_pubsub,
                ssp_cip_pubsub,  
                {utils.file_requester_ep:ssp_fr_endpoints,
                utils.file_server_ep:ssp_fs_endpoints},
                machine_uuid = msg.attributes[utils.machine_uuid],
                machine_cores = msg.attributes[utils.machine_cores],
                compute_devices = msg.attributes[utils.compute_devices],
                k = msg.attributes[utils.k],
                t_s = msg.attributes[utils.t_s]
                        ) 
                                
        ssp_alive_msg = utils.MsgWrapper(message = utils.ssp_alive,
            attributes = {
                utils.machine_uuid:remote_machine_uuid,
                utils.status_update:self.machines[remote_machine_uuid].status,
                utils.node_name:node_name,
                utils.compute_devices:msg.attributes[utils.compute_devices],
                utils.crVersion:msg.attributes[utils.crVersion],
                utils.machine_cores:msg.attributes[utils.machine_cores]
                   })
                                          
        self.cli_cip_router.send_multipart([sess_uuid, 
                            bytes(json.dumps(ssp_alive_msg.serialize(), 
                            cls = utils.BTEncoder),'utf-8')])
        
        for name, machine in self.machines.items():
            self.logger.info("CRClientServerManager.server_connect" +\
                    l_sep +\
                    " screen divisions for : " + name + \
                " are :" + str(machine.screen_coords))

        self.logger.info("CRClientServerManager.server_connect" +\
                    l_sep +\
                    ' responding to invitation to connect to ' + \
                            remote_machine_uuid) #+ ssp_addr)
        
        # set amount of time to wait to user prefs value
        
        
        #_______ESTABLISH CONNECTION WITH CHALLENGE/RESPONSE____________________________#
        
        # poll the new server session until it responds, then we know
        # its recving msgs from us and is ready to use.
        time_left = float(self.network_timeout)
        
        start_time = time.perf_counter()
        
        hello_msg = MsgWrapper(command = utils.hello,
                                attributes = {utils.machine_uuid:remote_machine_uuid})
        exp_backoff = 0.0
        
        while time_left:
            
            if time_left <= 0.0:
                
                #dooo something! Its broken!
                
                
                #set the status to unresponsive (read as dodgy) and continue 
                # anyway just in case it comes good.
                self.machines[remote_machine_uuid].status = utils.unresponsive
                
                break
                
            hello_msg.attributes[utils.message_uuid] = str(uuid.uuid4())
                
            self.cip_ssp_pubsub.send_string(json.dumps(hello_msg.serialize(), 
                            cls = utils.BTEncoder))
            
            try:
            
                response = ssp_cip_pubsub.recv_string(zmq.NOBLOCK)
                
                self.logger.info("CRClientServerManager.server_connect" +\
                    l_sep +\
                    "got hello response from server session process : " +\
                    remote_machine_uuid)
                    
                    
                break
                
            except zmq.ZMQError as e:
                
                if e.errno == zmq.EAGAIN:
                    
                    pass
            
            elapsed = time.perf_counter() - start_time
            time_left = float(self.network_timeout) - (elapsed)
            # formula :   Max_t * exp ( R_t / elapsed_time)
            # Max_t = max interval between sent msgs
            # R_t coefficient that governs how fast the backoff reaches Max_t,
            # a value of zero will make exp_backoff equal to Max_t at all times,
            # values that are very small but not zero make exp_backoff reach 
            # Max_t very very quickly, larger values, more slowly.
            exp_backoff = 2.0 * exp(-0.015 / elapsed)
            time.sleep(exp_backoff)
            
        
        if self.machines[remote_machine_uuid].status == utils.unresponsive:
            
            self.logger.warning("CRClientServerManager.server_connect" +\
                    l_sep +\
                    "Got no response from sending hello? to " +\
                    "ssp : " + remote_machine_uuid)
                    
        else:
            
            self.machines[remote_machine_uuid].status = utils.connected
        
            # we need to set system status to connectd here due to the configuration
            # of the main loop. the main loop would get stuck in its connecting state
            # unless we finally set status to connected here. Can't be done by just
            # setting the state of each machine to connected. Local machine is set to 
            # synced by default anyway.

            router_id_str = self.file_server.router_id.decode('utf-8')
        
            #get a copy of the file for transferring to decouple us from anything the user
            # might do (including resync, render etc, anything that might cause windows
            # to error if we've still got a long running transfer task with a file handle
            # locking the file.
        
            new_temp_file = upload_task[SESSION_FILES][MAIN_PROJECT_FILE]
        
            check_top_hash_msg = MsgWrapper(command = utils.init_session,
                s_uuid = sess_uuid,
                attributes = {
                    utils.machine_uuid:remote_machine_uuid,
                    utils.session_uuid:self.session_uuid.decode('utf-8'),
                    utils.top_hash:self.top_hash,
                    utils.resync:False,
                    utils.file_path:new_temp_file,
                    utils.router_id:router_id_str,
                    utils.load_trusted:self.load_trusted,
                    utils.upload_task:upload_task}
                                )
            check_top_hash_msg.attributes[utils.message_uuid] = str(uuid.uuid4())
            
            self.cip_ssp_pubsub.send_string(json.dumps(check_top_hash_msg.serialize(), 
                                cls = utils.BTEncoder))
            
            #Since we've just connected to another machine, we need to update the 
            # screen_coords for the local blend file. So send a msg to the client process
            # to make it update its screen coords.
        
        
            self.logger.info("CRClientServerManager.server_connect" +\
                        l_sep +\
                        "Finished initialising node: " + str(remote_machine_uuid))
                        
            #TODO:JIRA:CR-84: no state management here. Really need some time to put things
            # into a framework so we can have a quick method for deploying new features
            # across the network rather than using ad-hoc solutions like the one below (meants
            # to close the loop on a connect to a server by disconnecting the reqrep 
            # socket since we have successfully made the connection.
        
        
        
        
    def disconnect(self, s_uuid, msg):
        
        machine_uuid = msg.attributes[utils.machine_uuid]
        
        machine = self.machines.get(machine_uuid, None)
        
        if not machine is None: 
            
            msg.s_uuid = s_uuid
            
            machine.disconnect(msg)                    
    
                        
    def cancel_connect_remote_server(self, msg):
    
        try:
        
            disconnect_msg = MsgWrapper( command = utils.cancel_connection, 
                                            attributes = {'success':'cancel successful'}
                                                )
            
            self.connector_inproc.send_string(json.dumps(disconnect_msg.serialize(), 
                            cls = utils.BTEncoder))
        
        
        except:
        
            self.logger.warning("CRClientServerManager.cancel_connect_remote_server" +\
                l_sep +\
                "Failed to succesfully disconnect, taking this as the socket being dead")
                                
            disconnect_msg = MsgWrapper( command = utils.cancel_connection, 
                                            attributes = {'success':'cancel successful'}
                                                )
                                                
    def get_srcfile_copy(self, f_path):
        """ Copies fpath to a new location and returns the new path
        
        Arguments:
            f_path       -   string: file path that one wishes to copy from
        
        Returns:
            new_path   -   string: the new file path after copying the file
            
        Side Effects:
            Well it does copy a file to a new location that's determined in this function.
        
        Exceptions Raised:
            None... yet
        
        Description:
            This function serves to copy files to a new location for the purposes of 
            avoiding collisions during file transfer to other nodes. When nodes need to
            have a file pushed to them, conflicts can occur since the operation is 
            typically quite a long one and the risk of the user saving the file whilst 
            the file transfer is in progress is quite real. 
            
            This function is part of a larger system that mitigates that risk by copying
            the data to be sent to a special name that is not going to be known the user
            and which their application has no reference to. This allows the file
            transfer to proceed without risking a conflict with file handles (mainly a 
            windows issue).
            
            This function returns a new file path after copying the file in fpath. The 
            method is to simply copy the file to the same directory (in our system this 
            is supposed to be a temporary directory so that all files are cleaned up on 
            exit of the program). The file is given a new name of the following format:
            
            new_fpath = %tmpdir%\SESSION_UUID\tempXXXX.ext
            
            SESSION_UUID = the session uuid saved in the file
            XXX = a number that gets incremented if the attempt to copy the file fails
                for any reason. 
            ext = the file extension we're using, we could end up transferring a lot of 
                files, including textures, caches and so on, so we need not assume that
                the extension is known in advance. Best to keep this dynamic.
            
            Should the file fail to copy, the function tries again by incrementing the 
            XXXX suffix. 
            
        """
        
        ### GET A LIST OF ANY FILES WE'VE ALREADY COPIED
        # Here we find the folder in the temp directory that contains any files 
        # we've used for transferring to other nodes. It may be empty, it may contain
        # files that are copies of the main user files, we've got to pick the latest one
        # and try to save to that and return its path for use in the transfer.
        
        par_dir = os.path.dirname(f_path)
        session_uuid = os.path.basename(par_dir)
        abs_filepath, ext = os.path.splitext(f_path)
        #list all files in the directory the temp file is located in
        files = os.listdir(par_dir)
        
        #filter out all files that aren't of the desired extension (we may keep all sorts
        # of files in the session_uuid folder, we've got to be specific since the 
        # file we're about to send has been specifically requested to be sent.
        
        most_recent_copy = sorted(
            filter(
                lambda f: os.path.splitext(f)[-1] == ext and \
            'temp' in f, files ))
         
        if not most_recent_copy: #the directory looks empty then
            
            vers = '0001'
        else:
            
            if os.path.splitext(most_recent_copy[-1])[0].isdigit():
                
                vers = "{:0=4}".format(int(os.path.basename(most_recent_copy[-1])) + 1)
                
            else:
                
                vers = '0001'
            
            
        new_path = os.path.join(os.path.split(f_path)[0], "temp" + vers + ext)
            
        try:
            #here we aim to copy the current fpath to the vers file name
            shutil.copy2(f_path, new_path)
            
        except OSError:
            
            winerror = getattr(OSError, 'winerror', 0)
            
            if winerror == ERROR_SHARING_VIOLATION:
                
                # try try try again, but increment the version suffix to try copying
                # to a new file in the session uuid directory. 
                
                vers = "{:0=4}".format(int(os.path.basename(abs_filepath)) + 2)
                
                new_path = os.path.join(os.path.split(f_path), vers + ext)
                
                shutil.copy2(f_path, new_path)
                
                
            else:
                
                # failure, dismal failure, I guess we'd better fess up & tell the user
                # we blew it on this particular copy. 
                
                location = "CRClientServerManager.get_srcfile_copy"
                log_string = "OSError detected whilst trying to copy"+\
                            " : " + f_path
                
                handle_generic_except(location, log_string, self.logger)
                
                
        except:
        
            location = "CRClientServerManager.get_srcfile_copy"
            log_string = "Unexpected error while trying to copy a file for transferring"+\
                            " : " + f_path
            
            handle_generic_except(location, log_string, self.logger)
            
        return new_path
        #TODO: Error propagation back to user
    
                                                
    def resynchronise_nodes(self, sess_uuid, msg):
        """ Calls each connected node and commands them to re-download the blend file
        """
        
        #update the file path for the temp file. 
        
        nodes_to_resync = {
            uuid:self.machines.get(uuid) \
            for uuid in msg.attributes[utils.render_nodes]}
        
        for mach_uuid, machine in nodes_to_resync.items():
            
            if not mach_uuid == 'local' and machine is not None:
                #if a load is done with live machines
                # attached, we will need to do this here.          
                
                load_msg = MsgWrapper(command = utils.init_session,
                    s_uuid = sess_uuid,
                    attributes = {
                        utils.top_hash:msg.attributes[utils.top_hash],
                        utils.screen_coords:machine.screen_coords,
                        utils.machine_uuid:mach_uuid,
                        utils.load_trusted:self.load_trusted,
                        utils.resync:True,
                        utils.upload_task:msg.attributes[
                            utils.upload_task]}
                            )
                
                load_msg.attributes[utils.message_uuid] = str(uuid.uuid4())
                
                self.cip_ssp_pubsub.send_string( json.dumps(
                                load_msg.serialize(), 
                            cls = utils.BTEncoder))
        
        self.logger.info("CRClientServerManager.resynchronise_nodes: " +\
                l_sep +\
                'completed sending resync messages')
        
        
    def init_session(self, sess_uuid ,msg):
        """ Causes a session to be initialised
        
        This method operates to initialised a session, whether this is a saved
        session being loaded from disk, or a completely new session. It opens or saves 
        the cip blend file, configures the zmq sockets and creates directory structures
        where necessary.
        
        """
        
        import os
        
        self.render_jobs_queue = queue.Queue()
        self.session_uuid = sess_uuid #session_uuid is not a property
            #of the cip, the uuid is a key to multiple session objects
        self.top_hash = msg.attributes[utils.top_hash]
        self.screen_size = msg.attributes[utils.screen_size]
        self.load_trusted = msg.attributes[utils.load_trusted]
        upload_task = msg.attributes[utils.upload_task]
        resync = msg.attributes[utils.resync]
        
        compute_devices = get_compute_devices()
        
        
        self.session_path = msg.attributes[utils.session_path]
        
        
        #having initialised the directory and files, we now init the comms
        self.init_remote_sockets(msg)
        
        ######## INITIALISE FILE SERVER/REQUESTER ###################
        if not hasattr(self, 'file_server'):
            
            self.file_server = network_engine.CRFileServer(
                'client_node',
                self.logger, 
                self.context, 
                self.file_server_addr,
                self.machine_uuid, 
                self.start_port,
                self.port_range,
                self.network_timeout,
                local_public_key = self.client_key_pub,
                local_sec_key = self.client_key_secret
               )
            
        if not hasattr(self, 'file_requester'):
            
            self.file_requester = network_engine.CRFileRequest(
                'client_node',
                self.logger,
                self.context,
                self.machine_uuid,
                self.file_request_sock_addr,
                self.network_timeout,
                local_public_key = self.client_key_pub,
                local_sec_key = self.client_key_secret
                )
            

        # Calculate screen coordinates for all machines:
        

        num_cores = utils.get_machine_cores(self.logger)
        
        self.machines['local'] = CRServerMachine(
            self.session_uuid,
            self, 
            'local',
            self.cli_cip_router, 
            self.cip_ssp_pubsub,
            None, 
            [], 
            machine_uuid = 'local',
            machine_cores = num_cores,
            compute_devices = compute_devices
                    )
                                                
        # the local machine is always syncd since it has the original blend file                                         
        self.machines['local'].status = utils.synced
                                            
                                            
         ## UPDATE NODE STATUS
        # Sometimes on loading a file, the list of nodes can get out of sync, so 
        # we get each node to update 
                            
        for mach_uuid, mach in self.machines.items():
            
            #update blender main with our current list of connected nodes                  
            ssp_alive_msg = MsgWrapper(
                message = utils.ssp_alive,
                attributes = {
                    utils.machine_uuid:mach_uuid,
                    utils.node_name:mach.node_name,
                    utils.machine_cores:mach.machine_cores,
                    utils.status_update:mach.status,
                    utils.compute_devices:mach.compute_devices,
                    utils.crVersion:get_crowdrender_version()
                           }) 
                                       
            self.cli_cip_router.send_multipart([sess_uuid,
                bytes(json.dumps(ssp_alive_msg.serialize(), 
                            cls = utils.BTEncoder), 'utf-8')
                                            ])
        
        for name, machine in self.machines.items():
            self.logger.info("CRClientServerManager.init_session" +\
                l_sep +\
                "screen divisions for : " + name + \
                " are :" + str(machine.screen_coords))
        
        
        for mach_uuid, machine in self.machines.items():
            
            if not mach_uuid == 'local':
            
                #if a load is done with live machines
                # attached, we will need to do this here.          
            
                load_msg = MsgWrapper(
                    command = utils.init_session,
                    s_uuid  = sess_uuid,
                    attributes = {
                        utils.top_hash:self.top_hash,
                        utils.screen_coords:machine.screen_coords,
                        utils.resync:resync,
                        utils.machine_uuid:mach_uuid,
                        utils.upload_task:upload_task,
                        utils.load_trusted:self.load_trusted}
                            )

                load_msg.attributes[utils.message_uuid] = str(uuid.uuid4())
                
                self.cip_ssp_pubsub.send_string( json.dumps(
                                load_msg.serialize(), 
                            cls = utils.BTEncoder))

                    
                   
                                                
        self.logger.info("CRClientServerManager.init_session" +\
                l_sep +\
                'completed sending load_msg')
                    


        
    def init_remote_sockets(self, msg):
        """ Initialise the comms 
        """
        
        #TODO:JIRA:CR-38 consider the use of properties or use of a single function
        # to change the client address, we currently do this in a number of
        # places and that leads to confusion when debugging. 
        import ipaddress
        
        new_address_data = msg.attributes
        
        # check to see that we have the necessary addresses in the message otherwise
        # we'll leave them as they are.
        
        process_new_addresses = True 
        
        for addrs in (utils.local_address, utils.server_address, utils.session_uuid):
            
            # if all three addresses are present in the msg, the if statement logically
            # and's process_new_addresses with True three times leaving it true so 
            # we can execute the code to update these addresses. 
            # Otherwise it will be false and we don't.
            
            if addrs in msg.attributes:
                process_new_addresses = process_new_addresses & True
            else:
                process_new_addresses = process_new_addresses & False
        
        if process_new_addresses:
            self.access_key = new_address_data[utils.session_uuid]
        else:
            self.logger.debug("CRClientServerManager.init_remote_sockets" +\
                l_sep +\
                'No new addresses on init_remote sockets')
        
        #Checking to make sure the addresses are valid
        
        self.logger.debug("CRClientServerManager.init_remote_sockets" +\
                l_sep +\
                str(msg.attributes))
                
    def change_num_instances(self, s_uuid, msg):
        """ Set the number of instances to request to the value specified in the msg
        
        Arguments:
            s_uuid      :
            msg         :
        Returns:
            None
        Side Effects:
            Sends a request to discovery to change the number of instances being requested
        Exceptions:
            None
        Description:        
            Sends a request to the discovery server to change the number of blender grid
            nodes being requested to the value specified in the msg.attributes[utils.
            num_instances].
            This is used to scale up or down the number, it doesn't cause the server 
            start requesting nodes. For that use the 'start_rental_request' method
            
        
        """
        
        config_items = read_config_file([config.url_api, config.cr_token])
        
        cr_token = config_items[config.cr_token]
        url = config_items[config.url_api]
        
        headers = {
                'content-type': "application/json",
                'authorization':"Bearer " + cr_token,
                'cache-control': "no-cache",
                'Accept':"application/json"
                        }
                        
        payload = {
                    "query":"mutation($input: rentalInstanceCountInput) {"              +\
                    "updateRentalInstanceCount(input: $input) {"                        +\
                    "count"                                                             +\
                    "}} ", 
                    "variables":{
                    "input":{
                    "count": msg.attributes[utils.num_instances]
                            }
                           }
                    }
                    
        instances_request = {
        utils._uuid:msg.attributes[utils._uuid], 
        utils.http_request_type:"POST",        
        config.url_api:url,
        utils.headers:headers,
        utils.payload:json.dumps(payload)
        }
                
        insts_request = utils.MsgWrapper(command = utils.http_request,
            s_uuid = s_uuid,
            attributes = {utils.http_request:instances_request,
                        utils.on_complete:''}
            )
        
        self.http_request(insts_request)                        
        
        
        
                
    def start_rental_request(self, s_uuid, msg):
        """ Set the request_cloud_insts property to True to make requests for cloud nodes
        
        Arguments:
        Returns:
        Side Effects:
        Exceptions:
        Description:
        
        """
        self.request_cloud_insts = True
        

        self.request_discovery_refresh_rental(s_uuid, msg)      
        
        
    def stop_rental_requsts(self, s_uuid, msg):
        """ Set the request_cloud_insts property to False to stop requesting cloud nodes
        
        Arguments:
        Returns:
        Side Effects:
        Exceptions:
        Description:
        
        """
        self.request_cloud_insts = False
        
        config_items = read_config_file([config.url_api, config.cr_token])
        
        cr_token = config_items[config.cr_token]
        url = config_items[config.url_api]
        
        
        
        headers = {
                'content-type': "application/json",
                'authorization':"Bearer " + cr_token,
                'cache-control': "no-cache",
                'Accept':"application/json"
                        }
                #removed access_key as it was causing issues when changing file. 
                # BG can generate an id to use as the key for server sessions.

                        
        payload = {"query": "mutation($input : requestRentalInstancesInput) "           +\
                    " { updateRentalInstanceCount(input : {count:0}) {count}"           +\
                    "   requestRentalInstances (input: $input)"                         +\
                    " {accepted,"                                                       +\
                    "  refreshInterval,"                                                +\
                    "  renderCredit,"                                                   +\
                    "  numberOfBlenderGridNodes,"                                       +\
                    " machines { uuid, ip, port, accessKey,"                            +\
                    " computerName, local, active,"                                     +\
                    " machineData {crVersion, blVersion, renderDevices}}}}",
                    "variables": {
                    "input":{
                    "crVersion":msg.attributes[utils.crVersion],
                    "blVersion":msg.attributes[utils.blVersion]
                            }
                           }
                    }
                    
        instances_request = {
                utils._uuid:msg.attributes[utils._uuid], 
                utils.http_request_type:"POST",        
                config.url_api:url,
                utils.headers:headers,
                utils.payload:json.dumps(payload)
                }
        
        
        insts_request = utils.MsgWrapper(command = utils.http_request,
            s_uuid = s_uuid,
            attributes = {utils.http_request:instances_request,
                        utils.on_complete:msg.attributes[utils.on_complete]}
            )
        
        self.http_request(insts_request)
      
                
    def request_discovery_refresh(self, s_uuid, msg):
        """ Get the list of active nodes from discovery
        
        Arguments:
            msg:    MsgWrapper  -   cr msgwrapper object, must contain
                    s_uuid = unique id of the requesting peer session
                    attributes = {}
        Returns:
            nothing
            
        Side Effects:
            Calls http_request function passing in a request
            
        Exceptions:
            None
        
        Description: 
            Creates a request to the discovery server to get the list of active nodes
            which is then displayed to the user. This method forms part of a ping pong 
            request loop or heartbeat that keeps the user's visible list of available
            nodes up to date. If the user decides to use rental instances then a different
            request is used, see request_discovery_refresh_rental method.
        """
        config_items = read_config_file([config.url_api, config.cr_token])
        
        cr_token = config_items[config.cr_token]
        url = config_items[config.url_api]
        
        headers = {
                'content-type': "application/json",
                'authorization':"Bearer " + cr_token,
                'cache-control': "no-cache",
                'Accept':"application/json"
                        }
                        
        payload = {
            "query":"query {"                                                           +\
                "refreshInterval, "                                                     +\
                    "user {"                                                            +\
                        "renderCredit, "                                                +\
                        "numberOfBlenderGridNodes,"                                     +\
                        "machines {ip, "                                                +\
                            "uuid, computerName, local, active, accessKey,"             +\
                            " machineData {crVersion, blVersion, renderDevices}"        +\
                                   "} "                                                 +\
                        "}"                                                             +\
                "}"
                            
                           
                }
                        
        
        refresh_request = {
                utils._uuid:msg.attributes[utils._uuid], 
                utils.http_request_type:"POST",        
                config.url_api:url,
                utils.headers:headers,
                utils.payload:json.dumps(payload)
                }
                
        refr_request = utils.MsgWrapper(command = utils.http_request,
            s_uuid = s_uuid,
            attributes = {utils.http_request:refresh_request,
                        utils.on_complete:msg.attributes[utils.on_complete]}
            )
        
        self.http_request(refr_request)
        
    def refresh_user_credit(self, s_uuid, msg):
        """ Request an update for the user's credit from Blender Grid
        """
        
        config_items = read_config_file([config.url_api, config.cr_token])
        
        cr_token = config_items[config.cr_token]
        url = config_items[config.url_api]
        
        headers = {
                    'content-type': "application/json",
                    'authorization':"Bearer " + cr_token,
                    'cache-control': "no-cache",
                    'Accept':"application/json"
                  }
                            
        
        #request a refresh of the user's credit from Blender Grid
        payload_refr_credit = {
            "query":"""mutation {updateUserCredit {
                credit
                                            }} """
            
            }
            
        
        cred_refr_req = {
                    utils._uuid:msg.attributes[utils._uuid], 
                    utils.http_request_type:"POST",        
                    config.url_api:url,
                    utils.headers:headers,
                    utils.payload:json.dumps(payload_refr_credit)
                }
                
        cred_refr_msg = utils.MsgWrapper(command = utils.http_request, 
            s_uuid = s_uuid,
            attributes = {utils.http_request:cred_refr_req,
                        utils.on_complete:''})
                        
        
        self.http_request(cred_refr_msg)
        
        self.logger.debug("Requesting credit refresh")
        
                
    def request_discovery_refresh_rental(self, s_uuid, msg):
        """ Request the number of rented instances we want
        
        Arguments:
            msg:    MsgWrapper  -   cr msgwrapper object, must contain
                    attributes = {
                        
                        utils.num_instances:int - how many cloud nodes to start/use
                            }
                            
        Side Effects: 
            Causes the crowdrender server to request the user's credit from 
            blender grid.
        """
        
        
        
        if self.request_cloud_insts:
            
        
            num_cloud_instances = msg.attributes.get(utils.num_instances, None)
        
            config_items = read_config_file([config.url_api, config.cr_token])
        
            cr_token = config_items[config.cr_token]
            url = config_items[config.url_api]
        
        
        
            headers = {
                    'content-type': "application/json",
                    'authorization':"Bearer " + cr_token,
                    'cache-control': "no-cache",
                    'Accept':"application/json"
                            }
                    #removed access_key as it was causing issues when changing file. 
                    # BG can generate an id to use as the key for server sessions.
                    
            
            

            # we mst not set the cloud instances less than 0 when requesting.
            if num_cloud_instances is not None and num_cloud_instances > 0:
                        
                payload_inst_req = {
                    "query": """mutation($input : requestRentalInstancesInput,   
                             $input2 : rentalInstanceCountInput) {                      
                                requestRentalInstances (input: $input)                          
                                    {accepted, refreshInterval}                                       
                                updateRentalInstanceCount (input: $input2)
                                    {count}      
                            }""",
                            "variables": {
                            "input":{
                            "crVersion":msg.attributes[utils.crVersion],
                            "blVersion":msg.attributes[utils.blVersion],
                                    },
                            "input2":{"count":msg.attributes[utils.num_instances]}
                                    }
                                    }
            else:
                
                payload_inst_req = {
                    "query": """mutation($input : requestRentalInstancesInput) {                      
                                requestRentalInstances (input: $input)                          
                                    {accepted, refreshInterval}                                       
                                }""",
                            "variables": {
                            "input":{
                            "crVersion":msg.attributes[utils.crVersion],
                            "blVersion":msg.attributes[utils.blVersion],
                                    }
                                        }
                                    }
                                    
                    
            instances_request = {
                    utils._uuid:msg.attributes[utils._uuid], 
                    utils.http_request_type:"POST",        
                    config.url_api:url,
                    utils.headers:headers,
                    utils.payload:json.dumps(payload_inst_req)
                    }
                    
            
                
        
        
            insts_request = utils.MsgWrapper(command = utils.http_request,
                s_uuid = s_uuid,
                attributes = {utils.http_request:instances_request,
                            utils.on_complete:msg.attributes[utils.on_complete]}
                )
            
            self.http_request(insts_request)
        
        

        
    def request_discovery_login(self, s_uuid, msg):
        """ configures a login request for discovery server
        
        Arguments:
            s_uuid:     string     -    Unique id for the peer requesting the login
            msg:        MsgWrapper -    crowdrender msgwrapper object, should contain:
                attributes = { utils.user_name: string - obvious?
                                utils.password: string - obvious?
                }
                
        Returns:
        
        Side Effects: 
            calls http_request and passes the msg request in to start the actual request
        
        Exceptions:
        
        Description:
        
        """
        
        config_items = read_config_file([utils.url_auth])
        url_auth = config_items[utils.url_auth]
        
        user_name = msg.attributes[utils.user_name]
        password = msg.attributes[utils.password]
        
        headers = {
            'content-type': "application/x-www-form-urlencoded",
            'Accept':"application/json",
            'cache-control': "no-cache"
                    }
        payload = "username=" + user_name + "&password=" + password
        
        #create a request
        
        self.login_rqst = {
            utils._uuid:uuid.uuid4().int,        
            config.url_api:url_auth,
            utils.http_request_type:"POST",
            utils.headers:headers,
            utils.payload:payload
            }
        
        
        login_rqst_msg = utils.MsgWrapper(command = utils.http_request,
            s_uuid = s_uuid,
            attributes = {utils.http_request:self.login_rqst,
                        utils.on_complete:msg.attributes[utils.on_complete]}
            )
            
        self.http_request(login_rqst_msg)
        
    def logout(self, sess_uuid, msg):
        """ Log current user out of the CR system.
        """  
        
        "remove the user's access token from their file"
        write_config_file({config.cr_token:''})
          
            
    def http_request(self, msg):
        """ carry out request to discovery
        
        this handler invokes a thread to handle the request to login
        since this is a potentially longish I/O operation.
        """
        request = msg.attributes[utils.http_request]
        
        rqst_uuid = request[utils._uuid]
        
        request_thread = CRWebRequest(self.logger, self.context, 
                    self.http_request_sock_addr, request, 
                    timeout = self.http_refresh_interval * 3.0)
        
        self.http_requests[rqst_uuid] = (request_thread, msg)
        
    def handle_failed_file_req(self, msg):
        """ Handles the event of a file request failing
        
        Arguments: 
            msg:        utils.MsgWrapper -  Crowdrender message wrapper object, must have
                t_uuid:     string      - can be blank but where the request was for a 
                                        render tile, this needs to be set to the task
                                        id of the render to reply back to the engine 
                                        that a tile failed.
                attributes = {
                        utils.file_path:"path_to_render_tile" 
                        }
        Returns:
            nothing
        Side Effects:
            Sends msg to the main process announcing the failure of a file to be 
            transferred
        Exceptions:
            None
        
        Description:
            This method merely forwards the failed file transfer request to the 
            main process so that the user can be alerted. 
        """
        
        recv_fail_msg = MsgWrapper(message = utils.recv_fail,
            t_uuid = msg.t_uuid,
            attributes = {utils.file_path:msg.attributes[utils.file_path]}
            )
        
        
        
        self.cli_cip_router.send_multipart([msg.t_uuid, bytes(
            json.dumps(recv_fail_msg.serialize()),"utf-8")])
        
        
        
    
    def handle_disc_httpresp(self, msg):
    
        """ handle result of a http request to the discovery server
        
        Arguments:   
            msg:    MsgWrapper -    crowdrender msg, should contain
                attributes = {
                    utils.request_response: {}  - pydict containing results of request
                    utils._uuid: string         - unique id for the msg
                            }
                                     
        Returns:
            nothing
            
        Side Effects:
            Sends a msg to the blender main process containing the results of the
            request. 
            Removes an entry from the http_requests dictionary of the enclosing class.
            Sets the http_refresh_interval member of this object.
            
        Exceptions: 
            None
            
        Description: 
            This method handles the result of a http request, the incoming msg is 
            from the CRWebRequest thread that is associated with this request. An entry
            is removed from the http_requests dictionary that is associated with the 
            request and the request thread and original message.
            
        """
        response = msg.attributes[utils.request_response]
        _uuid = msg.attributes[utils._uuid]
        
        #get token so we can determine if we're loggedin right now.
        cr_token = read_config_file([config.cr_token]).get(config.cr_token, None)
        if cr_token == None: logged_in = False
        elif cr_token == '': logged_in = False
        else: logged_in = True
        
        
        #remove the request now we've dealt with it
        thrd, rqst_msg = self.http_requests.pop(_uuid) 
        
        #join thrd as we're done with it, catch the exception but don't do anything else
        try:
            thrd.join(timeout = 0.01)
        except:
            raise # TODO: CR_329 should set this to a logging statement when we've finished testing
            
        ## GET REFRESH INTERVAL
        # Where appropriate, interrogate the response for a refresh interval 
        # this allows the server to throttle all nodes if its being hammered
        # by requests. Much easier than asking all our users to update their software
        # to restore sanity to the system. 
        
        if type(response) is dict:
        
            data = response.get('data', None)
            #if we logged in for the first time, then we need to look for a token
            token = response.get(utils.token, None)
            error = response.get(utils.error, None)
            errors = response.get(utils.errors, [])
            
            #not every request requires to get the discovery refresh interval, only 
            # the requests that are periodic, which is pretty much only the 
            # discovery refresh request. 
            
            if data is not None:
                
                user = data.get(utils.user)
                update_num_instances_req = data.get(utils.updateRentalInstanceCount)                
                        
                if update_num_instances_req is not None:
                    
                    count = update_num_instances_req.get(utils.count)
                    
                    for err in errors:
                        self.logger.error("CRClientServerManaer.handle_disc_httpresp" +\
                            l_sep + " Error from discovery: " +\
                            str(err['message']))
                    
                     # get the response and form a msg
                    resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                        utils.requesting:self.request_cloud_insts,
                                    utils._uuid:_uuid,
                                    utils.logged_in:logged_in,
                                    utils.errors:errors})
                    
                
                elif user is not None:
                    
                    
                    
                    #the nodes should be in a python list, we need to make sure we actually have them
                    nodes = user.get(utils.machines, [])
                    
                    
                    #no point continuing if we can't get the refreshInterval, as it should be valid
                    # for all machines, including just the machine we're on
                    discovery_refresh = data.get('refreshInterval', None)
                    
                    # we need to set the enabled property based on the server value, 
                    # but only for cloud nodes.
                    if type(nodes) is list:
                    
                        for node in nodes:
                            cip_machine = self.machines.get(node[utils._uuid], None)
                            if cip_machine is not None and not node['local']:
                                cip_machine.enabled = node['active']
                    
                    if not discovery_refresh is None:
                        self.http_refresh_interval = discovery_refresh / 1000.0
                        self.logger.debug("CRClientServerManager.handle_disc_httpresp " +\
                        l_sep + " refresh for discovery requests set to " +\
                        str(self.http_refresh_interval) + " seconds.")
                        
                    # get the response and form a msg
                    resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                    utils.requesting:self.request_cloud_insts,
                                    utils._uuid:_uuid,
                                    utils.logged_in:logged_in,
                                    utils.errors:errors}
                        )
                        
                elif errors is not None:
                
                    for err in errors:
                        self.logger.error("CRClientServerManaer.handle_disc_httpresp" +\
                            l_sep + " Error from discovery: " +\
                            str(err['message']))
                
                    resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                    utils.requesting:self.request_cloud_insts,
                                    utils.errors:errors,
                                    utils._uuid:_uuid}
                        )
                    
                
                else:
                    
                    self.logger.debug("CRClientServerManager.handle_disc_httpresp " +\
                        l_sep + "Got weird response from discovery " +\
                        str(response))
                    
                    resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                    utils.requesting:self.request_cloud_insts,
                                    utils._uuid:_uuid}
                        )
            
            
            
            elif token is not None:
                self.logger.info("CRClientServerManager.handle_disc_httpresp " +\
                l_sep + " Successful login attempt")
                write_config_file({config.cr_token:token})
                
                # get the response and form a msg
                resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                    utils.requesting:self.request_cloud_insts,
                                        utils.logged_in:True,
                                    utils._uuid:_uuid}
                        )
                        
            elif error is not None:
                
                if error == utils.auth_required: logged_in = False
                elif error == utils.wrong_password: logged_in = False
                
                
                resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                    utils.requesting:self.request_cloud_insts,
                                        utils.logged_in:logged_in,
                                    utils._uuid:_uuid}
                        )
                self.logger.warning("CRClientServerManager.handle_disc_httpresp " +\
                    l_sep + "Error received from discovery :" + str(response))
                    
            elif errors:
                
                for err in errors:
                    self.logger.error("CRClientServerManaer.handle_disc_httpresp" +\
                        l_sep + " Error from discovery: " +\
                        str(err['message']))
                    
                    resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                    utils.requesting:self.request_cloud_insts,
                                    utils.errors:errors,
                                    utils._uuid:_uuid}
                        )
            
                        
            else:
                self.logger.warning("CRClientServerManager.handle_disc_httpresp " +\
                l_sep + " Unexpected msg from discovery" + str(response))
                
                resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                    utils.requesting:self.request_cloud_insts,
                                    utils._uuid:_uuid}
                        )
                  
            # send the response back to the user
        
            self.cli_cip_router.send_multipart([rqst_msg.s_uuid,
                bytes(json.dumps(resp_msg.serialize()),'utf-8')]) 
                
        else:
        
            #still send a response or the darn request loop stops. xD
            
            self.logger.warning("CRClientServerManager.handle_disc_httpresp " +\
                l_sep + " response content wasn't a json object " + str(response))
                
            resp_msg = utils.MsgWrapper(
                        message = rqst_msg.attributes[utils.on_complete],
                        attributes = {utils.request_response:response,
                                    utils.requesting:self.request_cloud_insts,
                                    utils._uuid:_uuid}
                        )
                
            self.cli_cip_router.send_multipart([rqst_msg.s_uuid,
                bytes(json.dumps(resp_msg.serialize()),'utf-8')]) 
        
        
    def handle_prog_update(self, msg):
        """ Handle the reported file receive progress during uploads
        
        Arguments:
            msg: -  string  -   a json formatted string representing a MsgWrapper object
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
            Sends a msg to the client informing it of the % progress of file transfer
            
        Exceptions Raised:
            None.
            
        Description:
            This method is part of the feedback loop during img file downloads that 
            reports the progress of the download of images from a node on a 0-100% scale. 
            
                                
        """
        
        
        self.cli_cip_router.send_multipart([msg.t_uuid, bytes(
            json.dumps(msg.serialize()),'utf-8')])           
    
    def handle_signal(self, signum, frame):
        """ handle a signal so shutdown can close all associated ssp's
        
        
        """
        self.logger.info("CRClientServerManager.handle_signal " + l_sep +\
            "Received signal:" + str(signum))
        if signum == signal.SIGTERM or signum == signal.SIGINT:
            self.shutdown()
            
    def shutdown(self, *args):
    
        # Log that we're exiting
        self.logger.info("CRClientServerManager.shutdown" +\
                l_sep +\
                'exiting ...')
        
        # Command the server interface process to shutdown
        
        close_command_obj = MsgWrapper(command = utils.exit, 
                            attributes = {utils.message_uuid:str(uuid.uuid4())}
                            )
        
        close_command = close_command_obj.serialize()
        #TODO:JIRA:CR-38 need a scaleable solution here, can't just go on 
        # adding hardcoded connections! 
        
        #This is a shutdown msg to all attached nodes.
        
        self.cip_ssp_pubsub.send_string(
                    json.dumps(close_command,
                    cls = utils.BTEncoder))
        
        # Exit from the file_server
        self.file_server_sock.send_json(close_command)
        self.file_request_sock.send_json(close_command)
        
        try:
        
            self.file_server.join(timeout = 1)
            self.file_requester.join(timeout = 1)
            
        except:
            
            location = "CRClientServerManager.shutdown"
            log_string =  "Exception caught while closing file server/requester threads"
            handle_generic_except(location, log_string, self.logger)
        
        if self.file_server.is_alive(): self.logger.error(
            "CRClientServerManager.shutdown" +\
                l_sep +\
            "file server seems to have hung, this processs may not exit")
                    
        
        
        #close our remote server sessions since we are shutting down.
        #TODO, use of select highly recommended, also a timeout on
        # how long a req will block the socket for. during testing
        # this channel it was discovered that you can't shut down the
        # client after a stalled request to connect to another machine
        # ( which uses this channel) since this socket blocks and 
        # hangs the client_interface process as the socket is still 
        # waiting for a response from the remote machine.
        # Also noticed that a reqrep socket seems to hang 
        # this process in this call below occasionally. Might
        # be due to the request to the remote server failing and
        # since reqrep requires a reply before a new request can be sent, 
        # the socket returns an error? The error trace returned gives the
        # following when the above happens:
        # zmq.error.ZMQError: Operation cannot be accomplished in current state
                
        # cause our main while loop to exit
        self.keep_alive = False
        
        for name, socket in self.polled_connections.items():
            self.logger.info("CRClientServerManager.shutdown" +\
                l_sep +\
                'unregistering : ' + name)
            try:
                self.poller.unregister(socket)
                socket.close(linger=0)
            except:
                self.logger.error("CRClientServerManager.shutdown" +\
                l_sep +\
                'failed to unregister : ' + name)
        
        #TODO - investigate whether we need to unbind and disconnect before
        # shutting down, we have sockets that are in states which keep this
        # routine from completing, possibly because they are attempting to 
        # connect or bind and haven't yet been able to do so. In this state,
        # it seems the zmq code won't listen to a close command.     
        
        #shut down the network interfaces and zmq.context
        
#         for name, socket in self.connections.items():
#             self.logger.info('closing : ' + name)
#             socket.close()
        self.logger.debug("CRClientServerManager.shutdown" +\
                l_sep +\
                "closing all sockets")  
          
        self.context.destroy(linger=0)
        
        self.logger.info("CRClientServerManager.shutdown" +\
                l_sep +\
                'client interface is shutting down')
        #logging module documentation on logger system requires 
        # a shutdown to be performed before application exit. 
        logging_shutdown()
        
    def handle_unit_tests(self, msg):
        
        msg.attributes[utils.message_uuid] = str(uuid.uuid4())
        self.cip_ssp_pubsub.send_string(utils.run_unit_tests)
        
    def fwd_nodes_by_uuid_rqst(self, sess_uuid, msg):

        msg.attributes[utils.message_uuid] = str(uuid.uuid4())
        msg.s_uuid = sess_uuid
        self.cip_ssp_pubsub.send_string(json.dumps(msg.serialize(), 
                            cls = utils.BTEncoder))
        
    def fwd_node_attrib_hashes(self, sess_uuid, msg):
        msg.attributes[utils.message_uuid] = str(uuid.uuid4())
        msg.s_uuid = sess_uuid
        self.cip_ssp_pubsub.send_string(json.dumps(msg.serialize(), 
                                        cls= utils.BTEncoder))
         
    def update_timeout_prefs(self, msg):
        
        self.network_timeout = msg.attributes[utils.timeout]       
        self.logger.info("CRClientServerManager.update_timeout_prefs" +\
                l_sep +\
                "updated network timeout preferences, " +\
            " new timout is :" + str(self.network_timeout) + " seconds")
        
        ser_msg = msg.serialize()
        
        self.file_server_sock.send_json(ser_msg, 
                            cls = utils.BTEncoder)
        
        
    
    def map_msg_to_function(self):
        
        self.msg_map = {
                utils.exit:self.shutdown,
                utils.disconnect:self.disconnect,
                utils.run_unit_tests:self.handle_unit_tests,
                utils.data_update:self.data_update,
                utils.connection_req:self.contact_server,
                utils.ready:self.server_connect,
                utils.init_addrs:self.init_remote_sockets,
                utils.init_session:self.init_session,
                utils.render:self.render, 
                utils.resync:self.resynchronise_nodes,
                utils.cancel_connection:self.cancel_connect_remote_server,
                utils.get_nodes_by_uuid:self.fwd_nodes_by_uuid_rqst,
                utils.get_node_attrib_hashes:self.fwd_node_attrib_hashes,
                utils.update_timeout_prefs:self.update_timeout_prefs,
                utils.hello_cip:self.handle_hello,
                utils.connect_failed:self.server_no_connect,
                utils.trying_again:self.try_again,
                utils.cancel_render:self.cancel_render,
                utils.render_engine_ready:self.render_engine_ready,
                utils.result_ready:self.result_ready,
                utils.view_ready:self.view_ready,
                utils.update_tile_size:self.update_tile_size,
                utils.http_request:self.http_request,
                utils.request_response:self.handle_disc_httpresp,
                utils.cancel_render:self.cancel_render,
                utils.discovery_refresh:self.request_discovery_refresh,
                utils.discovery_refresh_rental:self.request_discovery_refresh_rental,
                utils.discovery_login:self.request_discovery_login,
                utils.recv_fail:self.handle_failed_file_req,
                utils.progress_update:self.handle_prog_update,
                utils.update_node_status:self.update_node_status,
                utils.discovery_request_rental:self.start_rental_request,
                utils.start_rental_request:self.start_rental_request,
                utils.stop_rental_request:self.stop_rental_requsts,
                utils.change_num_instances:self.change_num_instances,
                utils.logout:self.logout,
                utils.updateUserCredit:self.refresh_user_credit
                        }
                        
            



