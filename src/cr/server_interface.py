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

import bpy, time, subprocess, sys, os, json, uuid, signal, atexit
from queue import Queue, Empty
from subprocess import TimeoutExpired
from threading  import Thread

from . utils import CRWebRequest, get_computer_name, get_base_app_version, handle_generic_except
from . utils import get_computer_os, get_crowdrender_version, timed_out, setup_logging
from . utils import MsgWrapper
from . config import write_config_file, read_config_file
from . rules import get_cycles_devices, get_blender_version, get_compute_devices
from . rules import get_blender_executable
from . logging import  l_sep, logging_shutdown
import zmq
from . import utils, network_engine, config

import faulthandler

crowdrender = sys.modules[__package__]

####  CREATE CRASH LOGS #####
fault_text_file_path = os.path.expanduser("~") +\
     os.path.normpath("/cr/logging/sip_faults.txt")

if os.path.exists(fault_text_file_path):
    fault_text_file = open(fault_text_file_path, "wb")
else:
    utils.mkdir_p(os.path.split(fault_text_file_path)[0])
    fault_text_file = open(fault_text_file_path, "wb")

faulthandler.enable(file = fault_text_file)

def check_process_alive(processes, logger):
     
 
    list_pids = list()
    
    for id in processes:
        list_pids.append(id)
 
    for id in list_pids:
            
        proc = processes[id]
        
        # if a server sess process dies, its returncode will
        # no longer be None and this if statement will 
        # be executed giving us the error messages
        
        # if a process is dead, then take the following action.
        if not proc.poll() is None:
            
            # NOTE: because the returncode will be 0
            # we can't simply use if poll(): since poll
            # would return 0 which is logically false
            # even though the process is dead (thats
            # what a return code of 0 seems to mean).
            
            # Get the error msg from the dead processes 
            # handler
            
            logger.error("UTILS:check_process_alive" + l_sep + " " +\
                            proc.name + ' with PID ' + \
                            str(id) + ' has died')
                            
            #Better do a check here since its happened before
            # that the process has exited and the stdout is 
            # None meaning that you need to check first that
            # you can read from stdout.
                               
            if not proc.stdout is None:
                
                try:
                    err_dump = proc.stdout.readlines()
                    
                    for line in err_dump:
                        logger.error(line.decode("utf-8"))
                    
                except:
                    
                    logger.warning("UTILS:check_process_alive" + l_sep +\
                     " Error trying to read from stdout :" +\
                                   proc.name)
            
                
            else:
                logger.info("UTILS:check_process_alive" + l_sep +\
                    " stdout was none on process exit for : "+\
                            proc.name + " , nothing to log.")
            
            
            
            
            # logger.error('process:' + proc.name + " " + err_dump.decode("utf-8"))
                             
            
            # We don't want to contiunally log msgs about a dead
            # process, removing it from the processes dict removes
            # our only remaining reference to it and so it gets
            # gc'd as well as not showing up in the logs repeatedly.
            processes.pop(id)
            
def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    #out.close()

class CRServerMachine:
    """ Object to represent a server machine
    Contains a handle to the process as well as the sockets to communicate
    with the process
    """
    
    def __init__(self, process):
        self.process = process
    
class CRMachineManager:
    """ Client Server Manager
    """
    def __init__(self):
    
        ###  DEFINE AND INSTANTIATE MEMBERS OF THE CLASS
          
        # get access_key, and the cr_token. If the access_key is
        # a random uuid then this server is hosted 
        # in the cloud and we need to give the server's machine uuid this value
        # rather than an automatically generated one.
        
        ## COMMAND LINE ARGUMENTS
        ind_pass = sys.argv.index("--")
        args = sys.argv[ind_pass + 1:]
        
        import argparse
        
        parser = argparse.ArgumentParser(
            description='Crowdrender Server - accepts connections from other nodes')
        
        parser.add_argument('-p', required = False, default=True,
                    help="Set to True if this is a physical node, only set " +\
                    "this to False if its a cloud based node")
        parser.add_argument('-ak', required = False, default = "",
                    help= "Access Key, used for P2P and cloud based nodes and "+\
                    " is used to authenticate a connection request")
        parser.add_argument('-ct', required= False, default = "",
                    help= "Crowdrender Token, used to authenticate this node to post " +\
                        "to the discovery server and show this node as active")
        parser.add_argument('-t', required= False, default = "server_int_proc",
                            help= "Type of background process to "+\
                            "configure, use server_int_proc to start a headless server.")
                        
                    
        processed_args = parser.parse_args(args)

        c_line_args = vars(processed_args)
        
        if not c_line_args['p'] or c_line_args['p'] == True:
            self.persistent = True
        else: 
            self.persistent = False
        
        self.access_key = c_line_args['ak']
        cr_token = c_line_args['ct']
        
        # if no token was given on the command line, then we need to get it from 
        # somewhere!
        if not cr_token:
            #get the token from the config file if there is one.
            cr_token = read_config_file(["cr_token"])["cr_token"]
            
        else:
            write_config_file({config.cr_token:cr_token})
            
        
        # If there is an access key, set the machine_uuid to this - used when the node
        # is virtual, i.e. cloud based. These types of nodes don't have unique 
        # hardware machine uuids (they're actually all the same).
        
        if self.access_key:
            self.machine_uuid = self.access_key
        else:
            self.machine_uuid = utils.get_machine_uuid()
            
        ## SETUP SIGNAL HANDLERS
        signal.signal(signal.SIGTERM, self.handle_signal)
        atexit.register(self.shutdown)
        
        self.connections = {}
        self.pending_conn_rqsts = {} # used to store requests for connection
        # synchroniser = CRSyncrhoniser()
        self.bound_addresses = list() # list of bound endpoints for listening socket
        self.logger = setup_logging('server_interface', 
             base_app = get_base_app_version())
        self.http_req_sock_endpt = 'http_req_sock' 
        self.setup_network()
        
        
        
        
        self.machine_cores = utils.get_machine_cores(self.logger)
        
        self.logger.info("machine uuid is :" + self.machine_uuid)
        
        self.map_msg_to_function()
        
        self.server_sessions = {}
        self.server_sess_out_threads = {}
        self.http_refresh_interval = 30.0
    
        self.keep_alive = True
       
        ### POST TO WEB SERVICE
        
        #register this machine with the discovery service
        self.register_post()
        
        ###  START MAIN LOOP
        self.service_interface_process()
        
    def register_post(self):
        """ Register this machine with the discovery server
        """
    # give this operator a uuid so that in the event of overlapping 
        # calls (if you really want to go there) the responses can 
        # be matched back to the operator that made the call.
        rqst_uuid = uuid.uuid4().int
        
        config_items = read_config_file([config.url_api, config.cr_token])
        
        cr_token = config_items[config.cr_token]
        cr_disc_url = config_items[config.url_api]
        
        if cr_token == '':
            
            pass
            # do nothing, there's no token and no reason to batter discovery with
            # requests that won't authorize
            
            
        else:
        
            #cr_disc_url = "http://discovery.crowd-render.com/api/v0/graph" #remove
        
                        
        
            headers = {'cache-control': 'no-cache',
                        'Authorization': "Bearer " + cr_token,
                        'content-type': 'application/json', 
                        'Accept': 'application/json'}
                    
            payload =  {
                "query": "mutation($input: machineInput)"+\
                " { registerMachine(input: $input) {refreshInterval}}",
                "variables": {
                    "input": {
                        "uuid": self.machine_uuid,
                        "computerName": get_computer_name(),
                        "accessKey": self.access_key,
                        "local":self.persistent,
                        "machineData": {
                            utils.crVersion: get_crowdrender_version(),
                            "renderDevices": get_cycles_devices(),
                            utils.blVersion: get_blender_version(),
                            "operatingSystem": get_computer_os(),
                        
                                        }
                            }
                            }
                        }


                    
            request = {
                    utils._uuid:rqst_uuid, 
                    utils.http_request_type:"POST",        
                    config.url_api:cr_disc_url,
                    utils.headers:headers,
                    utils.payload:json.dumps(payload)
                    }
                
            CRWebRequest(self.logger, self.context, self.http_req_sock_endpt, request,
                    timeout=self.http_refresh_interval * 3.0)
        
    def update_post(self):
        """ 
            
        """
        
        rqst_uuid = uuid.uuid4().int
        config_items = read_config_file([config.url_api, config.cr_token])
        
        cr_token = config_items[config.cr_token]
        cr_disc_url = config_items[config.url_api]
        
        if cr_token == '':
            
            pass
            # do nothing, there's no token and no reason to batter discovery with
            # requests that won't authorize
            
            
        else:
        
            
            headers = {'cache-control': 'no-cache',
                        'Authorization': "Bearer " + cr_token,
                        'content-type': 'application/json', 
                        'Accept': 'application/json'}
                    
            payload =  {
                "query": "mutation($input: machineInput)"+\
                " {updateMachine(input: $input) {refreshInterval}}",
                "variables": {
                    "input": {
                        "uuid": self.machine_uuid,
                        "computerName":get_computer_name(),
                            }
                            }
                        }

                    
            request = {
                    utils._uuid:rqst_uuid, 
                    utils.http_request_type:"POST",        
                    config.url_api:cr_disc_url,
                    utils.headers:headers,
                    utils.payload:json.dumps(payload)
                    }
                
            CRWebRequest(self.logger, self.context, self.http_req_sock_endpt, request, 
                timeout=self.http_refresh_interval * 3.0)
        
        
        
    
    def handle_hello(self, sess_uuid, msg):
        """ Respond to a hello msg from the client, used when establishing connections
        """

        response_msg = utils.MsgWrapper(message = utils.hello_sip,
                            t_uuid = msg.t_uuid,
                            attributes = {utils.machine_uuid:self.machine_uuid})
                        
        self.cli_sip_router.send_multipart([sess_uuid,
            bytes(json.dumps(response_msg.serialize()),'utf-8')])
    
        self.logger.info("responding to hello request..")
        
     

    
    def setup_network(self):
        # Define the sockets required to communicate with client        
        self.context = zmq.Context()    
        
        # TODO:JIRA:CR-38 Multiple server support also suggests we should look at multiple
        #client support? This code is designed only to support a single connected client.
        user_preferences = bpy.context.preferences
        addon_prefs = user_preferences.addons[crowdrender.package_name].preferences
        
        self.start_port = addon_prefs.start_port
        self.port_range = addon_prefs.port_range
        
        # # Connection for PUB SUB Server_Interface_Processe to Client_Interface_Process
        
        self.cli_sip_router = self.context.socket(zmq.ROUTER)
        self.cli_sip_router.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.cli_sip_router.bind("tcp://127.0.0.1:" + str(self.start_port + 2))
        self.connections['cli_sip_router'] = self.cli_sip_router
        # self.sip_cli_pubsub = self.context.socket(zmq.PUB)
#         self.sip_cli_pubsub.bind('tcp://127.0.0.1:' + str(self.start_port)) # old port 9000')
#         self.connections['sip_cli_pubsub'] = self.sip_cli_pubsub
#         
#         # # Connection for PUB SUB Server_Interface_Processe to Client_Interface_Process        
#         self.cli_sip_pubsub = self.context.socket(zmq.SUB)
#         self.cli_sip_pubsub.connect('tcp://127.0.0.1:' + str(self.start_port + 2)) # old port 9002')
#         self.cli_sip_pubsub.setsockopt(zmq.SUBSCRIBE,b'')
#         self.connections['cli_sip_pubsub'] = self.cli_sip_pubsub
        
        # # Connection for REQ_REP Client_Interface_Process to Server_Interface_Process
        # self.cip_sip_reqrep = self.context.socket(zmq.REP)
#         self.cip_sip_reqrep.bind('tcp://127.0.0.1:9021')
        
        # # Connection for REQ_REP Client_Interface_Process_Remote to Server_Interface_Process
        self.cipr_sip_reqrouter = self.context.socket(zmq.ROUTER) #Port 9022
        self.connections['cipr_sip_reqrouter'] = self.cipr_sip_reqrouter        
        self.cipr_sip_reqrouter.bind("tcp://*:" + str(self.start_port + 6))       
        
        # # Connection for PUB_SUB Server Interface Process to Server_Session_Process
        self.sip_ssp_pubsub = self.context.socket(zmq.PUB) #Port 9023
        self.sip_ssp_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.sip_ssp_pubsub.bind('tcp://127.0.0.1:' + str(self.start_port + 7)) # old port 9023')
        self.connections['sip_ssp_pubsub'] = self.sip_ssp_pubsub   
        
        self.ssp_sip_pubsub = self.context.socket(zmq.SUB) #Port 9024
        self.ssp_sip_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.ssp_sip_pubsub.connect('tcp://127.0.0.1:' + str(self.start_port + 8)) # old port 9024')
        self.ssp_sip_pubsub.setsockopt(zmq.SUBSCRIBE,b'')
        self.connections['ssp_sip_pubsub'] = self.ssp_sip_pubsub

        # # Connection for REQ_REP Server Session Process to Server_Interface_Process
        self.ssp_sip_reqrep = self.context.socket(zmq.REP) #Port 9007
        self.ssp_sip_reqrep.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.ssp_sip_reqrep.bind('tcp://127.0.0.1:' + str(self.start_port + 5)) # old port 9007')
        self.connections['ssp_sip_reqrep'] = self.ssp_sip_reqrep
        
        # Connection for PUB_SUB Client_Interface_Process to Server_Interface_Process
        self.cip_sip_pubsub = self.context.socket(zmq.SUB) #Port 9025
        self.cip_sip_pubsub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.cip_sip_pubsub.setsockopt(zmq.SUBSCRIBE,b'')
        self.cip_sip_pubsub.connect('tcp://127.0.0.1:' + str(self.start_port + 9)) # old port 9025')
        self.connections['cip_sip_pubsub'] = self.cip_sip_pubsub
        
        self.http_req_sock = self.context.socket(zmq.DEALER)
        self.http_req_sock.bind("inproc://" + self.http_req_sock_endpt)
        self.connections['http_req_sock'] = self.http_req_sock
        
        # Initialize poll set for the receiving ports only
        self.poller = zmq.Poller()
        self.poller.register(self.cip_sip_pubsub , zmq.POLLIN)
        self.poller.register(self.cipr_sip_reqrouter , zmq.POLLIN)
        self.poller.register(self.http_req_sock, zmq.POLLIN)
        
        self.poller.register(self.ssp_sip_reqrep , zmq.POLLIN)
        self.poller.register(self.ssp_sip_pubsub , zmq.POLLIN)
        self.poller.register(self.cli_sip_router , zmq.POLLIN)       
        
        self.logger.info("Network Interfaces Initialised")
    
    def start_server_session(self, type, client_uuid = '', s_uuid=''):
        """
        
        """
        
        exe = get_blender_executable()
        
        server_session_process = subprocess.Popen(
            [
             exe, 
             "-b", 
             "-noaudio",#--factory_startup
             "-P",
             os.path.normpath(os.path.split(__file__)[0] + "/svr_ssn_start.py"),
             '--', 
             'remote', 
             client_uuid, 
             "server_session_proc"
            ], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT)
        
        server_session_process.name = 'server session'
        
        self.server_sessions[client_uuid] = server_session_process
        sess_queue = Queue()
        sess_out_thread = Thread(
            target=enqueue_output, 
            args=(server_session_process.stdout, sess_queue))
        sess_out_thread.daemon = True
        sess_out_thread.start()
        
        self.server_sess_out_threads[client_uuid] = (sess_out_thread, sess_queue)
        
        # Log that we have started a session and what its PID is
        for name in self.server_sessions:
            # If the process successfully starts we log a msg stating it
            
            if self.server_sessions[name].poll() is None:
            
                self.logger.info( 'server session :'+ name + \
                                '  started with PID ' + \
                                str(self.server_sessions[name].pid) 
                                )
                        
            else:
                self.logger.error( 'server session :' + name + \
                                ' failed to start')
        
        return server_session_process
    
        
    def service_interface_process(self):
    
        last_poll = time.perf_counter()
        
        while(self.keep_alive):
        
            
            self.process_msgs()
            
            for sess_id, msg_attr in self.pending_conn_rqsts.items():
                
                session_uuid = bytes(msg_attr[utils.session_uuid],'utf-8')
                
                #send hello
                hello_msg = utils.MsgWrapper(command = utils.hello_ssp, 
                        s_uuid = session_uuid)
                self.sip_ssp_pubsub.send_string(json.dumps(hello_msg.serialize()))
                
            # TODO: Might want to do this every second not every loop!! 
            check_process_alive(self.server_sessions, self.logger)
            
            for thread, sess_queue in self.server_sess_out_threads.values():
                #the_process.stdout.flush()
                try:
                    print("NODE: ", 
                        get_computer_name(), 
                        sess_queue.get_nowait()
                        )
                    sess_queue.task_done()
                         
                except Empty:
                    pass
                    
                    
            if timed_out(last_poll, self.http_refresh_interval):
            
                last_poll = time.perf_counter()
                self.update_post()
         
        
        ## EXIT
        # Shutdown networking
        
        self.poller.unregister(self.cipr_sip_reqrouter)
        
        self.poller.unregister(self.ssp_sip_reqrep)
        
        self.poller.unregister(self.ssp_sip_pubsub)
        self.poller.unregister(self.cip_sip_pubsub)
        self.poller.unregister(self.cli_sip_router)
        
#         self.poller.unregister(self.cip_sip_reqrep)
        
        #shut down the network interfaces and zmq.context        
        for name, socket in self.connections.items():
            self.logger.info('closing : ' + name)
            socket.close()
            
        self.context.term()
        
        self.logger.info('server interface is shutting down')        
        
        logging_shutdown()       
        
                
            
    def process_msgs(self):
    
        #sometimes this is put in a 'try/except handler'
        #the timeout is in milliseconds
        self.socks = dict(self.poller.poll(10))
        
        try:
            
            if self.cipr_sip_reqrouter  in self.socks:
            #self.logger.info("receiving cipr_sip_reqrouter message")
            
                msg_parts_raw = self.cipr_sip_reqrouter.recv_multipart(zmq.NOBLOCK)
                
                #need to pop the identity cause this will cause an exception if its 
                # decoded as a string. We pop it and put it where it needs to go, then
                # process the rest of the msg.
                
                # msg_parts_raw format is 
                # msg[0] = bytes identity
                # msg[1] = bytes empty/delimiter
                # msg[2] = bytes payload = json encapsulated object (connection request in 
                # this case.
                msg = MsgWrapper.deserialize(msg_parts_raw)
                
                msg.attributes[utils.router_id] = msg_parts_raw.pop(0)
                
                
                if msg.command in self.msg_map:
                    #now process the message
                    self.logger.info("cipr_sip_reqrouter: " +\
                        msg.command)
                    
                    func = self.msg_map[msg.command]
                    
                    func(msg)
                    
            
        #for now, retain a message data block for each interface
        
            if self.ssp_sip_reqrep  in self.socks:
                self.logger.info("receiving self.ssp_sip_reqrep message")
                ssp_sip_reqrep_message = self.ssp_sip_reqrep.recv()
                #now process the message  
            
            #for now, retain a message data block for each interface
            if self.cli_sip_router in self.socks:
                
                self.logger.info("receiving self.cli_sip_router message")
                            
                sess_uuid, msg_raw = self.cli_sip_router.recv_multipart()            
                
                cli_sip_router_message = utils.MsgWrapper.deserialize(
                            msg_raw)
                
                if cli_sip_router_message.command in self.msg_map:
                    
                    self.logger.info("cli_sip_router:: " + \
                                        cli_sip_router_message.command)
                    
                    func = self.msg_map[cli_sip_router_message.command]
                
                    func(sess_uuid, cli_sip_router_message)    
                    
                
                
            #for now, retain a message data block for each interface
            if self.ssp_sip_pubsub  in self.socks:
                
                ssp_sip_pubsub_message = utils.MsgWrapper.deserialize(
                                self.ssp_sip_pubsub.recv_string())
                                
                if ssp_sip_pubsub_message.message in self.msg_map:
                    
                    self.logger.info("ssp_sip_pubsub:: " + \
                                        str(ssp_sip_pubsub_message.message))
                    
                    func = self.msg_map[ssp_sip_pubsub_message.message]
                
                    func(ssp_sip_pubsub_message)    
                #now process the message  
    
            #for now, retain a message data block for each interface
            if self.ssp_sip_reqrep  in self.socks:
                self.logger.info("receiving self.ssp_sip_reqrep message")
                self.ssp_sip_reqrep_message = self.ssp_sip_reqrep.recv()
                #now process the message   
                
            if self.cip_sip_pubsub  in self.socks:
                # self.logger.info("receiving self.cip_sip_pubsub message")
                cip_sip_pubsub_message = utils.MsgWrapper.deserialize(
                    self.cip_sip_pubsub.recv_string() 
                        )
                
                self.logger.info("cip_sip_pubsub:: " + \
                                        cip_sip_pubsub_message.command)
                
                
                #now process the message  
                if cip_sip_pubsub_message.command in self.msg_map:
                    
                    func = self.msg_map[cip_sip_pubsub_message.command]
                
                    func(cip_sip_pubsub_message)
                    
            if self.ssp_sip_pubsub in self.socks:
            
                # self.logger.info("receiving self.cip_sip_pubsub message")
                ssp_sip_pubsub_message = utils.MsgWrapper.deserialize(
                    self.ssp_sip_pubsub.recv_string()
                        )
                
                self.logger.info("ssp_sip_pubsub:: " + \
                                        str(ssp_sip_pubsub_message.message))
                
                
                #now process the message  
                if ssp_sip_pubsub_message.message in self.msg_map:
                    
                    func = self.msg_map[ssp_sip_pubsub_message.message]
                
                    func(ssp_sip_pubsub_message)
                                
            
            if self.http_req_sock in self.socks:
                
                
                
                msg = utils.MsgWrapper.deserialize(
                                 self.http_req_sock.recv_string())
                
                
                if msg.message in self.msg_map:
                
                    func = self.msg_map[msg.message]
                    
                    func(msg)
                    
                else:
                    
                    self.logger.warning("CRMachineManager.process_msgs" + l_sep +\
                        " received msg that didn't have a valid 'message' field" +\
                                        msg)
                
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
    
    
    def start_remote_session(self, msg):
        
        #first determine if this session has an id and if so, does the request
        # have the same one? We'll totally ignore this request if it doesn't 
        # match the session_uuid we received on the command line. 
        
        if not self.access_key == 'server_int_proc':
            request_sess_id = msg.attributes[utils.access_key]
            
            if not request_sess_id == self.access_key:
                self.logger.error("CRMachineManager.start_remote_session: " +\
                    "request had the wrong access_key so I ignored it. " +\
                    "client had access_key : " + str(request_sess_id) +\
                    "server has : " + self.access_key)
                return
        
        if msg.attributes[utils.machine_uuid] in self.pending_conn_rqsts:
            #kill existing process if its there and continue, but log this
            self.logger.info("Got a duplicate connection request, trying to start" +\
                " a new process..")
            if msg.attributes[utils.machine_uuid] in self.server_sessions:
                
                curr_proc = self.server_sessions[msg.attributes[utils.machine_uuid]]
            
                # the nice way first, lets try to gently shut it down.
                curr_proc.terminate()
                
                self.server_sess_out_threads.pop(
                        msg.attributes[utils.machine_uuid])
            
                try:
            
                    (stdout, stderr)  = curr_proc.communicate(timeout=5)
            
                except TimeoutExpired:
                    # looks like the process hung, we'll kill it instead
                    curr_proc.kill()
                
                    
                    #remove the duplicate request
            self.pending_conn_rqsts.pop(msg.attributes[utils.machine_uuid])
                
                
        elif msg.attributes[utils.machine_uuid] in self.server_sessions:
            #kill existing process and start a new one, but log
            self.logger.info("Got a duplicate conn rqst for an already running " +\
                "session, killing the old session and starting a new one")
            
            # get a ref to the current process to terminate it.
            
            curr_proc = self.server_sessions[msg.attributes[utils.machine_uuid]]
            
            self.server_sess_out_threads.pop(
                        msg.attributes[utils.machine_uuid])
            # the nice way first, lets try to gently shut it down.
            curr_proc.terminate()
            
            try:
            
                (stdout, stderr)  = curr_proc.communicate(timeout=5)
            
            except TimeoutExpired:
                # looks like the process hung, we'll kill it instead
                curr_proc.kill()
            
        else:
            # store the request and attempt to fulfill it. We'll eventually remove
            # the stored request when its fufilled or fails permanently
            self.logger.info("Checked that session_uuid is not already running " +\
                "or requested: passed")
        
        #now we've cleared any duplicate requests of processes, here we add our latest 
        # request.        
                
        self.pending_conn_rqsts[msg.attributes[utils.machine_uuid]] =\
                msg.attributes
            
        
        
        
        self.logger.info("about to start a process for "+\
             str(msg.attributes[utils.machine_uuid]))
        
        #TODO, here we have explicitly set client_address to one value,
        # for the prototype, this is fine, but its likely this will fall 
        # apart when it comes to multiple clients. Have to think about 
        # how we can ensure each client can be given a session. We currently 
        # have to set a member variable (here self.client_address) to contain
        # the remote client's ip address. We have to do this since we wait
        # for the ssp we spawn to answer that it is up and running. Then 
        # we can initialise it and hand off to the remote client. We'd have 
        # to do this multiple times with multiple remote clients and we'd 
        # need to be very careful about not corrupting state.
        
        
        self.client_machine_uuid = msg.attributes[utils.machine_uuid]
        
        client_uuid = msg.attributes[utils.machine_uuid]
        s_uuid = msg.attributes[utils.session_uuid]
        
        self.start_server_session('remote', client_uuid, s_uuid)
        
        # #crude but effective, wait until the process has initiated its 
        # # sockets which connect to this process, then update its connections
        # # to the requesting process
        
        # time.sleep(4)
        
        
        

    def ssp_alive(self, msg):
        """ Handles msg from a new process that it is alive and ready for the client
        """
    
        self.logger.info('server session ' + \
            msg.s_uuid.decode('utf-8') + ' is alive')
        
        
        # Tell the new session to initialise its sockets using the following data
        init_sockets_msg = utils.MsgWrapper(command = utils.client_address_update,
                                s_uuid = msg.s_uuid,
                                attributes = {
                                            utils.local_address:self.bound_addresses,
                                            utils.machine_uuid:self.client_machine_uuid,
                                            utils.access_key:self.access_key}
                                                        )
                                                     
        self.sip_ssp_pubsub.send_string( json.dumps (init_sockets_msg.serialize(),
                                                    cls = utils.BTEncoder ) )
        
        
        self.logger.info("updating sockets on " +\
            str(self.server_sessions[msg.attributes[utils.client_uuid]]))
        
#         self.cipr_sip_reqrouter.send_string(json.dumps(reply_test_msg.serialize()))
        
    def server_session_ready(self, msg):
        """Reply back to client with server session ready msg
        """
        #TODO, imagining in the future that this will be a reply including
        # a dynamic address to connect to? So perhaps a port number?
        
        compute_devices = get_compute_devices()
        
        self.logger.info("sending ready msg to requesting client")
        
        server_ready_msg = utils.MsgWrapper(message = utils.ready,
                s_uuid = msg.s_uuid,
                public_key = msg.public_key,
                attributes = {utils.machine_uuid:msg.attributes[utils.machine_uuid],
                utils.machine_cores:self.machine_cores,
                utils.server_endpoint:msg.attributes[utils.server_endpoint],
                utils.crVersion:get_crowdrender_version(),
                utils.compute_devices:compute_devices,
                utils.k:msg.attributes[utils.k],
                utils.t_s:msg.attributes[utils.t_s]})
        
        client_identity = self.pending_conn_rqsts[msg.attributes[utils.client_m_uuid]]\
            ['router_id']
        # format for send to a REQ socket from a router
        # msg parts are as follows
        # msg[0] = bytes - identity value
        # msg[1] = bytes - empty/delimiter
        # msg[2] = bytes - payload
        
        msg_parts = [client_identity,
                    b'',
                    bytes(json.dumps(
                            server_ready_msg.serialize(),
                            cls = utils.BTEncoder), 
                            'utf-8')
                    ]
        
        self.cipr_sip_reqrouter.send_multipart(msg_parts)
        
        self.pending_conn_rqsts.pop(msg.attributes[utils.client_m_uuid])
        
        self.logger.info("Completed handling request for new connection")
            
        

    
    def handle_discovery_httpresp(self, msg):
        """ Gets the response of a http request from the request thread
        
        Side Effects: sets the http_refresh_interval
        """
        
        self.logger.debug("CRMachineManager.handle_discovery_httpresp" + l_sep +\
                    " Received the following response from a http request "+\
                        str(msg.attributes[utils.request_response]))
                        
        response = msg.attributes.get(utils.request_response, None)
        
        if type(response) is dict:
            data = response.get('data', None)
            
            if not data is None:
            # get the result of the query for registerMachine or updateMachine
                query_result_register = data.get(
                    'registerMachine', None
                                        )
                query_result_update = data.get('updateMachine', None)
                
                # if we've got a query for and update process it here.
                if not query_result_update is None:
                    http_refresh_interval = query_result_update.get(
                                                                'refreshInterval', None
                                                                    )
                    
                    if not http_refresh_interval is None:
                        
                        # The response from discovery.crowd-render.com is in millisecs
                        # we have to convert it as we use seconds
                        self.http_refresh_interval = http_refresh_interval / 1000.0
                        #print("refresh interval is now: ", self.http_refresh_interval)
                
                # process a result of a query to register a machine
                elif query_result_update is None and not query_result_register is None:
                    
                    http_refresh_interval = query_result_register.get(
                                                                'refreshInterval', None)
                    
                    if not http_refresh_interval is None:
                        
                        # The response from discovery.crowd-render.com is in millisecs
                        # we have to convert it as we use seconds
                        self.http_refresh_interval = http_refresh_interval / 1000.0
                        #print("refresh interval is now: ", self.http_refresh_interval)
                    
                # process the case where the result is none for both, try to re-register
                
                elif query_result_update is None and query_result_register is None:
                    
                    self.register_post()
                    print("Registering this machine again")
                    
                    
                    
                
    def handle_signal(self, signum, frame):
        """ handle a signal so shutdown can close all associated ssp's
        
        
        """
        self.logger.info("CRMachineManager.handle_signal " + l_sep +\
            "Received signal:" + str(signum))
        if signum == signal.SIGTERM or signum == signal.SIGINT:
            self.shutdown()
                            
    
    def shutdown(self, msg=None):
    
        # Log that we're exiting
        
        self.logger.info('Exiting......')
        
        # Command the server interface process to shutdown
        # self.sip_ssp_pubsub.send_string(utils.exit)
        
        close_msg = utils.MsgWrapper(command = utils.exit)
        
        try:
        
            self.sip_ssp_pubsub.send_string(json.dumps(close_msg.serialize()))
        
        except:
        
            self.logger.info('Failed to send close msg to ssp (sip_ssp_pubsub on port XX23)')
            
        for proc in self.server_sessions.values():
            
            if not proc.stdout is None:
                
                try:
                    stdout = proc.stdout.readlines()
                    
                    self.logger.info(stdout)
                    
                except:
                    
                    self.logger.warning("Error trying to read from stdout for proc :" +\
                                   proc.name)
                    
            else:
                self.logger.info("stdout was none on process exit for : "+\
                            proc.name + " , nothing to log.")
                
            proc.terminate()
        
        time.sleep(1)
        
        # cause our main while loop to exit
        self.keep_alive = False
        #close polling objects
#         self.poller.unregister(self.cip_sip_reqrep)
        
        
    def map_msg_to_function(self):
        
        self.msg_map = {utils.ssp_alive:self.ssp_alive,
                        utils.exit:self.shutdown,
                        utils.start_server_session:self.start_server_session,
                        utils.connection_req:self.start_remote_session,
                        utils.ready:self.server_session_ready,
                        utils.hello_sip:self.handle_hello,
                        utils.request_response:self.handle_discovery_httpresp}
            


    
