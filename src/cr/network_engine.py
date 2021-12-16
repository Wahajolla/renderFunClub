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
network_engine - manage network traffic between nodes

Purpose

This module presents an interface to easily transmit messages, commands and
data across a network. The aim is to have a backwards compatible, modular
interface that permits ease of communication with other nodes

Input/Output

The input to the module can be a message, command or data in the form of a 
file or a buffer from memory. 
The output of the file is the same as its input types, messages, commands
and data. 

How

Through the classes exported by this module, an interface is exposed that
allows sending and receiving data to and from other nodes on the network. 
This is done in such as way that the module has a consistent interface with 
semantics that don't change, but still allowing the underlying mechanism of 
what protocols are used to vary as development demands.


Modules Imported

Classes Exported

Exceptions Raised

Functions Exported


"""

#Std Library imports
import threading, os, zmq, json, time, atexit, uuid, pickle, tempfile, shutil
import sys
from hashlib import algorithms_guaranteed
from statistics import mean, stdev
from math import exp, ceil

#Crowdrender imports
from . import utils
from . utils import timed_out, MsgWrapper
from . utils import address, public_key, handle_generic_except
from . logging import l_sep


#MODULE CONSTANTS
IF_IPADDR = 2
DEVICE_NAME = 1
HARDWARE_PORT_NAME = 0
LAST = -1
CHUNK_SIZE = 64000 # chunk_size is in BYTES
ERROR = b'ERROR'
PIPELINE = 32
TIMEOUT_RETRIES = 4# at the default timeout of 30 secs gives enough 
# time to recover from tcp zero windows

action = 'action'
all_offsets = 'all_offsets'
cancel = 'cancel'
chunk_request_timeout = 'chunk_request_timeout'
chunks_rcvd = 'chunks_rcvd'
complete = 'complete'
data = 'data'
duration = 'duration'
fail_timeout = 'fail_timeout'
file_id = 'file_id'
file_total_rcvd = 'file_total_rcvd'
func = 'func'
func_args = 'func_args'
f_handle = 'f_handle'
f_size = 'f_size'
f_write_to = 'f_write_to'
handle_recv_data = 'handle_recv_data'
info_request_timeout = 'info_request_timeout'
in_buffer = 'in_buffer'
max_to_duration = 'max_to_duration'
msg_attribs = 'msg_attribs'
offsets = 'offsets'
peer_id = 'peer_id'
req_start_time = 'req_start_time'
req_to_duration = 'req_to_duration'
round_trip_time = 'round_trip_time'
session_id = 'session_id'
start_time = 'start_time'
task_id  = 'task_id'
temp_file = 'temp_file'
time_outs = 'time_outs'
timeout_retries ='timeout_retries'

SEEK_SET = 0 # start of the stream (the default); offset should be zero or positive
SEEK_CUR = 1 # current stream position; offset may be negative
SEEK_END = 2 # end of the stream; offset is usually negative

## Hash Algorithm selection

if not 'blake2b' in algorithms_guaranteed:
    raise RuntimeError("Required hashing algorithm blake2b not found")
    
else:
    from hashlib import blake2b as hash_algorithm

class CRFileServer(threading.Thread):
    """ Multi client file server """
    
    running = False
    
    def __init__(self, mode, logger, zmq_context, inproc_address, 
                    machine_uuid, start_port, port_range, network_timeout,
                    local_addresses =[],
                    local_public_key = b'',
                    local_sec_key = b''):
                 
        """ start a fileserver, creates a new thread
        
        mode: str: either 'client_node' or 'server_node', determines whether the server 
            should bind or connect its socket used for data xfr.
        logger: logging.logger object: Used by the calling process to log events
        zmq_context: zmq.Context obj: Used for creating sockets
        local_addresses: list('ip_addr:port') : A list of endpoints to bind to 
            (if mode = 'server_node')
        inproc_address: string :the address of the inproc socket used to communicate 
            between the calling process and this file server.
        machine_uuid: string: The uuid of this computer, used, hmmmm where is that used?
        start_port: int: the starting port used to offset from when binding (used when
            mode = 'render_node' only)
        port_range: int: the number of ports to use starting with the start_port.
        
        """
        
        
        
        threading.Thread.__init__(self, daemon= True)
        
        atexit.register(self.close)
        
        self.handlers = {utils.connect_node:self.connect_node,
                        utils.exit:self.close,
                        utils.update_timeout_prefs:self.update_timeout_prefs,
                        utils.disconnect:self.disconnect_node}
                        
        
        self.render_node_eps = list()
        
        self.logger = logger
        self.network_timeout = network_timeout
        self.endpoints = list()
        self.machine_uuid = machine_uuid
        self.local_public_key = local_public_key
        self.local_sec_key = local_sec_key
        
        self.zmq_c = zmq_context
        
        ####### CONNECT INPROC SOCKET (CONTROL CHANNEL) ######### 
        
        self.inproc = self.zmq_c.socket(zmq.PAIR)
        self.inproc.connect("inproc://" + inproc_address)
        
        
        #Create the socket we'll use to send/recv data
        
        self.router = self.zmq_c.socket(zmq.ROUTER)
        self.router.curve_secretkey = self.local_sec_key
        self.router.curve_publickey = self.local_public_key
        self.router.set(zmq.IDENTITY, bytes(machine_uuid, 'utf-8'))
        self.router.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.router.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 20)
        self.router_id = self.router.IDENTITY
        
        
        if mode == 'client_node':
        
            pass
                                                
            
        
        elif mode == 'server_node':
            
            self.router_ports = {}
            self.router.curve_server = True
            
                                                

            
            self.router_ports = self.router.bind_to_random_port(
                "tcp://*",
                min_port = start_port + 15,
                max_port = start_port + 15 + port_range)
                                                
            self.logger.info("CRFileServer.__init__ " + l_sep +\
                "File server bound its router socket to :" + \
                str(self.router.LAST_ENDPOINT) + ":" +\
                str(self.router_ports))
            
            # rather than returning all the endpoints bound to, we just return the
            # last one, endpoints are not actually used by the client, only the 
            # port number since the client will only attempt a connect on the 
            # ip it originally contacted the server on.
            
            self.endpoints.append(
                (str(self.router.LAST_ENDPOINT), self.router_ports))
        
        
        
        ###########################################
        
        
        self.poller = zmq.Poller()
        
        self.poller.register(self.router, zmq.POLLIN)
        self.poller.register(self.inproc, zmq.POLLIN)
        
        self.file_streams = {}
        self.file_st_buffer = PIPELINE * CHUNK_SIZE
        
        self.send_progress = {}
        
        self.start()
        
    def run(self):
        
        self.running = True
        
        while self.running:
            
            try:
                
                events = dict(self.poller.poll(16))
                
                if self.inproc in events:
                    
                 
                    json_msg = self.inproc.recv_json(zmq.NOBLOCK)
                    
                    msg = MsgWrapper.deserialize(json_msg)
                    
                    if msg.command in self.handlers:
                        
                        self.handlers[msg.command](msg)
                     
                     
                if self.router in events:
                    #handle router msgs
                    keep_receiving = PIPELINE
                    
                    while keep_receiving:
                        
                       
                        msg = self.router.recv_multipart(zmq.NOBLOCK)
                        
                        keep_receiving -= 1
                        
                        if msg[1] == b'HELLO?':
                            
                            self.router.send_multipart([msg[0], b'HELLO!'])
                        #we don't want to react to b'HELLO' msgs
                        elif msg[1] == b'HELLO!':
                            pass
                        else:
                            self.file_rqst_handler(msg)
                            
                    
                    
                open_streams = self.file_streams.copy()
                        
                for stream_name, fstream in open_streams.items():
                    
                    fstream.close()
                    self.file_streams.pop(stream_name, None)
                    
                
                
                
            except zmq.ZMQError as e:
                
                if e.errno == zmq.EAGAIN:
                                
                    pass
                
                elif e.errno == zmq.ETERM:
                    break
                    
                else:
                    location = "CRFileServer.run"
                
                    log_string = " unexpected zmq error encountered" +\
                                " whilst polling."
                  
                
                    handle_generic_except(
                        location= location, log_string=log_string, logger=self.logger)
                
                    
                    
            except:
                
                location = "CRFileServer.run"
                
                log_string = " unknown error encountered" +\
                                " whilst polling."
                  
                
                handle_generic_except(
                    location= location, log_string=log_string, logger=self.logger)
                
                
                
        #clean up
         
        #unregister and close all sockets
        self.poller.unregister(self.router)
        self.poller.unregister(self.inproc)    
        
        #close
        self.router.close(linger = 0)
        self.inproc.close(linger = 0)
        
        
        #close all file streams
        for files in self.file_streams.values():
        
            files.close()   
            
        self.logger.info("CRFileServer.run:" +l_sep+\
            "shutdown..")
            
            
    def file_rqst_handler(self, msg):
        
        """ handle request for a chunk of a file
        
        expected format of msgs
        msg[0] = identity
        msg[1] = request type - b'HELLO?', b'HELLO!', b'FILE_INFO', b'FILE_DATA'
        msg[2] = FID (file ID)
        msg[3] = offsets = (offset, chunk size)
        msg[4] = request uuid
        
        """
        
        #identity = msg[0]
        fid = msg[2].decode('utf-8')
        filesize = os.path.getsize(fid)
        dumps = pickle.dumps
        send_multipart = self.router.send_multipart
        
        
        if not fid in self.file_streams:
            
            try:
            
                self.file_streams[fid] = open(
                    fid, 'rb', buffering=self.file_st_buffer)
                
                
            except OSError as e:
                
                #fail message
                rep = [msg[0], ERROR, msg[2], [b''], msg[4]]
                
                send_multipart(rep)
                
                self.logger.warning(
                    "OSError: " + e.strerror +\
                    " : This happened " +\
                    "whilst handling a request for " + str(msg[1]))
        
        read = self.file_streams[fid].read
        seek = self.file_streams[fid].seek
        
        if msg[1] == b"FILE_INFO":
            
            rep = [msg[0], msg[1], msg[2], 
                filesize.to_bytes(
                    (filesize.bit_length() // 8) + 1, byteorder='big'),
                        msg[4]]
            
            self.logger.info(
                "Crowdrender: Responding to request for file info for: " +\
                 str(fid))
            
            send_multipart(rep)
        
        elif msg[1] == b'FILE_DATA':
            
            offsets = pickle.loads(msg[3])
            
            
            for offset_data in offsets:
                
                seek(offset_data[0], os.SEEK_SET)
                data = read(offset_data[1])
                hash_digest = hash_algorithm(data).digest()
                
                send_multipart(
                    [msg[0],
                     msg[1],
                     msg[2],
                     dumps(offset_data[0]),
                     msg[4],
                     data,
                     hash_digest]
                            )


    def update_timeout_prefs(self, msg):
        
        self.network_timeout = msg.attributes[utils.timeout]
        
        self.logger.info("CRFileServer.update_timeout_prefs:" +l_sep+\
            " updated the network timeout value to :" +\
            str(self.network_timeout) + " seconds")
            
    def close(self, msg=None):
    
        self.logger.info("CRFileServer.close:" +l_sep+\
            " shutting down..")
        self.running = False
        
    def disconnect_node(self, msg):
        """ Disconnects a requesting node from the file server.
        
        """
        
        node_endpoints = msg.attributes[utils.server_endpoint]
        
        
        for endpoint in node_endpoints:
            
            try:
                self.router.disconnect(endpoint[address])
                if endpoint in self.render_node_eps:
                    self.render_node_eps.remove(endpoint)
                self.logger.info("CRFileServer.disconnect_node:" +l_sep+\
                    " is disconnected from: " + endpoint[address])
            except zmq.ZMQError as e:
                if e.errno == 2:
                    self.logger.info("CRFileServer.disconnect_node:" +l_sep+\
                    " was disconnected from: " + endpoint[address] +\
                    " with an exception, seems the disconnect failed with " +\
                    e.strerror)
                    
        #CLOSE EXISTING ROUTER SOCKET            
        self.poller.unregister(self.router)
        self.router.close(linger=0)
        
        ## CREATE NEW ROUTER SOCKET
        # done so that peer tables are reset and the any new connection to 
        # a node that failed on connect will work, otherwise router - router
        # sockets suffer corrupt peer tables and msgs are dropped silently
        self.router = self.zmq_c.socket(zmq.ROUTER)
        self.router.curve_secretkey = self.local_sec_key
        self.router.curve_publickey = self.local_public_key
        self.router.setsockopt(zmq.IDENTITY, bytes(self.machine_uuid, 'utf-8'))
        self.router.setsockopt(zmq.LINGER, 0)
        self.router.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.router.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 20)
        self.poller.register(self.router, zmq.POLLIN)
        
        for endpoint in self.render_node_eps:
            self.router.curve_serverkey = bytes(endpoint[public_key], 'utf-8')
            self.router.connect(endpoint[address])
                
        
    def connect_node(self, msg):
        """ connects the file server to a render node
        this method connects the file server to a render node using the address given
        in the msg argument. The msg argument needs to be a utils.MsgWrapper object
        with an attribute called utils.server_endpoint which stores the endpoint that
        the files server connects to as a string in the following format:
        
            '0.0.0.0:00000' 
            
        This is then used to connect to the render node. The zmq socket that is 
        used is of the ROUTER type and is connected to multiple render nodes, each 
        endpoint is stored in a list.
        
        """
        
        node_endpoints = msg.attributes[utils.server_endpoint]
        node_router_id = msg.attributes[utils.requesting_id]
        node_name = msg.attributes[utils.node_name]
        
        for endpoint in node_endpoints:
            
            #this is just a check to alert us to the fact we're attempting to connect
            # to a node we've already connected to. nothing more, nothing less :D
            
            if endpoint in self.render_node_eps:
                self.logger.info("CRFileServer.connect_node:" +l_sep+\
                    " already connected to this node: " +\
                         str(endpoint[address]))
                         
               
            self.router.curve_serverkey = bytes(endpoint[public_key], 'utf-8')
            self.router.connect(endpoint[address])
            
            # see if the node is actually listening now.
            if self.challenge_resp(node_router_id, msg, endpoint[address]):
        
                self.render_node_eps.append(endpoint)
                self.logger.info("CRFileServer.connect_node:" +l_sep+\
                    " connected to: " + str(endpoint[address]))
        
            else:
                # if we timeout we just disconnect from the endpoint and assume
                # its dead. 
                
                disconnect_msg = MsgWrapper(command = utils.disconnect,
                    attributes = {utils.server_endpoint:[endpoint[address]]}) 
                    
                self.disconnect_node(disconnect_msg) 
        
                self.logger.warning("CRFileServer.connect_node:" +l_sep+\
                    " could not establish comms for : " +\
                            str(endpoint[address]) + " so it was disconnected")
                conn_failed = MsgWrapper(message = utils.connect_failed,
                    s_uuid = msg.s_uuid,
                    attributes = {utils.node_name:msg.attributes[utils.node_name],
                                utils.node_address:endpoint[address].split(":")[0]})
                    
                self.inproc.send_json(conn_failed.serialize())
                #TODO - what if the challenge times out, what do we do then?
            
    def challenge_resp(self, router_id, ch_msg, endpoint):
    
        #wait for router sockets to come up
        start_time = time.perf_counter()
        
        time_left = self.network_timeout
        
        waiting_for_server = True
        
        exp_backoff = 0.0
        
        while waiting_for_server:
            
            if time_left <= 0.0:
                
                #outta here!
                fail_msg = MsgWrapper(message = utils.connect_failed,
                    s_uuid = ch_msg.s_uuid,
                    attributes = {
                        utils.node_name:ch_msg.attributes[utils.node_name],
                        utils.node_address:endpoint})
                
                self.inproc.send_json(fail_msg.serialize())
                
                waiting_for_server = False
                
                self.logger.error("CRFileServer.challenge_resp:" +l_sep+\
                    " Could not connect to :" + router_id)
                
                ret_value = 0
                
                break
            
            self.router.send_multipart([bytes(router_id, 'utf-8'), b'HELLO?'])
            
            try:
                
                msg = self.router.recv_multipart(zmq.NOBLOCK)
                
                # pass file chunk requests to appropriate handler
                # if we get them whilst calling up another node
                
                if not msg[0] == bytes(router_id, 'utf-8'):
                    
                    
                    if msg[1] == b"fetch": 
                        self.file_rqst_handler(msg)
                    
                    continue
                    
                #only finalise if the hello resp came from the node we're 
                # interested in
                elif msg[1] == b'HELLO!':
                    
                    waiting_for_server = False
                    self.logger.info("CRFileServer.challenge_resp:" +l_sep+\
                        "File Requester responded, "+\
                        " starting file server")
                    ret_value = 1
                    
                else:
                    #highly inprobably we'd get here, but not impossible, so
                    # cover the case where a node could be getting requests
                    # for chunks before the server is ready. This is supposed
                    # to be blocked by the file requester waiting until the 
                    # file server is connected, but you never know :0
                    
                    if msg[1] == b"fetch": 
                        self.file_rqst_handler(msg)
                
            except zmq.ZMQError as e:
                
                if e.errno == zmq.EAGAIN:
                    
                    pass
                
            except AssertionError:
                
                raise
            
            elapsed = time.perf_counter() - start_time
            time_left = float(self.network_timeout) - (elapsed)
            # formula :   Max_t * exp ( R_t / elapsed_time)
            # Max_t = max interval between sent msgs
            # R_t coefficient that governs how fast the backoff reaches Max_t,
            # a value of zero will make exp_backoff equal to Max_t at all times,
            # values that are very small but not zero make exp_backoff reach 
            # Max_t very very quickly, larger values, more slowly.
            exp_backoff = 2.0 * exp(-1.0 / elapsed)
            time.sleep(exp_backoff)
        
        return ret_value
        
            
        
        
class CRFileRequest(threading.Thread):
    """ A file server that serves multiple requesters simultaneously.
        The file server runs in a separate thread and can serve the same file to 
        multiple requesters or multiple files to multiple requesters at the same
        time.
        
        Arguments
        
        mode: string: 'client_node' or 'server_node', determines whether the sockets used
            bind or connect to enable comms where a NAT enabled device is between the
            client/server nodes. 
        logger: logging.logger object: used to log msgs to the parent thread's log file
        zmq_context: zmq.Context object: Used to create sockets, pollers for comms
        machine_uuid: Unique machine Uuid as determined in the parent thread, used to
            identify this node to other nodes and enable msg routing.
        inproc_address: string :address to use with the PAIR socket, enables the file
            server and parent thread to communicate.
        server_router_address: string : optional, needed when running the file requester
            on a client node and is the address of the server node.
        local_addresses: list(string)): A list containing the addresses of the 
            network interfaces on this machine, used only when mode = 'server_node' and
            ensures that all nics are used by the file requester.
            
            
    """
    
    running = False
    
    def __init__(self,
                mode, 
                logger,
                zmq_context,
                machine_uuid,
                inproc_address,
                timeout,
                server_router_id = '',
                server_router_address = '',
                local_addresses = list(),
                start_port = 0,
                port_range = 0,
                local_public_key = b'',
                local_sec_key = b''):
        
        threading.Thread.__init__(self, daemon= True)
        
        # temporary directory for storing all transferring files, 
        # keeps uploading/downloading files separate from files in use by the system.
        self.temp_dir = tempfile.TemporaryDirectory() 
        
        atexit.register(self.close)
        
        self.handlers = {utils.update_timeout_prefs:self.update_timeout_prefs,
                    utils.exit:self.exit,
                    utils.file_transf_req:self.file_transf_req,
                    utils.connect_node:self.connect_node,
                    utils.disconnect:self.disconnect_node,
                    utils.cancel:self.cancel_all_tasks} 
                    
        self.render_node_eps = list()
        
        self.timeout = timeout
        
        self.logger = logger
        self.zmq_c = zmq_context
        self.endpoints = list()
        self.machine_uuid = machine_uuid
        self.local_public_key = local_public_key
        self.local_sec_key = local_sec_key
        self.file_server_ready = False  
        self.recv_tasks = {}
        
        ####### CONNECT INPROC SOCKET (CONTROL CHANNEL) #########
        
        self.inproc = self.zmq_c.socket(zmq.PAIR)
        self.inproc.connect("inproc://" + inproc_address)
        
        self.poller = zmq.Poller()
        
        self.poller.register(self.inproc, zmq.POLLIN)

        self.logger.info("CRFileRequest.__init__:" +l_sep+\
            "File Requester connected its inproc channel")
        
         ####### CONNECT OR BIND ROUTER SOCKET (DATA CHANNEL) #########
         
        self.router = self.zmq_c.socket(zmq.ROUTER)
        self.router.set(zmq.IDENTITY, bytes(machine_uuid, "utf-8"))
        self.router.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.router.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 20)
        self.router.curve_secretkey = self.local_sec_key
        self.router.curve_publickey = self.local_public_key
        #self.router.setsockopt(zmq.ROUTER_MANDATORY, 1)
        self.poller.register(self.router, zmq.POLLIN)
        
        ## SET MODE
        # Determines whether the underlying sockets will bind or connect, important
        # for establishing connections.
        
        if mode == 'server_node':
            
            self.router.curve_server = True
            
            self.router_ports = self.router.bind_to_random_port(
                "tcp://*",
                min_port = start_port + 15,
                max_port = start_port + 15 + port_range
                )
                
            self.endpoints.append(
                (str(self.router.LAST_ENDPOINT), self.router_ports))
            
            self.server_router_id = server_router_id
            
            self.logger.info("CRFileRequest.__init__:" +l_sep+\
                "File Requester bound its router socket to :" + \
                str(self.router.LAST_ENDPOINT) +  ":" +\
                str(self.router_ports))
            
                                        
        elif mode == 'client_node':
            
            pass
                                      
        
        else:
             # mode was wrong, programming error!                    
            raise RuntimeError("File server mode incorrect")
        
        
        ## GO! 
        # Ready to start so do so ;)
        self.start()
    
    def close(self):
    
        self.running = False
            
    def disconnect_node(self, msg):
        """ Disconnects a requesting node from the file server.
        
        """
        
        node_endpoints = msg.attributes[utils.server_endpoint]
        
        
        for endpoint in node_endpoints:
            
            try:
                self.router.disconnect(endpoint[address])
                if endpoint in self.render_node_eps:
                    self.render_node_eps.remove(endpoint)
                self.logger.info("CRFileRequest.disconnect_node:" +l_sep+\
                    " is disconnected from: " + endpoint[address])
            except zmq.ZMQError as e:
                if e.errno == 2:
                    self.logger.info("CRFileRequest.disconnect_node:" +l_sep+\
                    " was disconnected from: " + endpoint[address] +\
                    " with an exception, seems the disconnect failed with " +\
                    e.strerror)
        
        #CLOSE EXISTING ROUTER SOCKET
        self.poller.unregister(self.router)
        self.router.close(linger=0)
        
        ## CREATE NEW ROUTER SOCKET
        # done so that peer tables are reset and the any new connection to 
        # a node that failed on connect will work, otherwise router - router
        # sockets suffer corrupt peer tables and msgs are dropped silently
        self.router = self.zmq_c.socket(zmq.ROUTER)
        self.router.curve_secretkey = self.local_sec_key
        self.router.curve_publickey = self.local_public_key
        self.router.setsockopt(zmq.IDENTITY, bytes(self.machine_uuid, 'utf-8'))
        self.router.setsockopt(zmq.LINGER, 0)
        self.router.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.router.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 20)
        self.poller.register(self.router, zmq.POLLIN)
        
        for endpoint in self.render_node_eps:
            self.router.curve_serverkey = bytes(endpoint[public_key], 'utf-8')
            self.router.connect(endpoint[address])
            
        
    def challenge_resp(self, router_id, msg, endpoint):
        
        #wait for router sockets to come up
        start_time = time.time()
        time_left = self.timeout
        ret = 0
        node_name = msg.attributes[utils.node_name]
        
        waiting_for_server = True
        
        while waiting_for_server:
            
            if time_left <= 0.0:
                
                #outta here!
                fail_msg = MsgWrapper(message = utils.connect_failed,
                    s_uuid = msg.s_uuid,
                    attributes = {
                        utils.node_name:msg.attributes[utils.node_name],
                        utils.node_address:endpoint.split(":")[0]})
                
                
                self.inproc.send_json(fail_msg.serialize())
                
                waiting_for_server = False
                
                self.logger.error("CRFileRequest.challenge_resp:" +l_sep+\
                    " Could not connect to :" + router_id)
                
                ret = 0
                
                break
            
            
            
            try:
                
                self.router.send_multipart(
                    [bytes(router_id, 'utf-8'), b'HELLO?'])
                
                msg = self.router.recv_multipart(zmq.NOBLOCK)
                
                #assert msg[0] == bytes(router_id, 'utf-8')
                
                if msg[1] == b'HELLO!':
                    
                    waiting_for_server = False
                    self.file_server_ready = True
                    self.logger.info("CRFileRequest.challenge_resp:" +l_sep+\
                    "File Server responded, starting request")
                    #return 1, file server is up!
                    ret = 1
                else:
                    
                    self.logger.debug("CRFileRequest.challenge_resp:" +l_sep+\
                        "Got unexpect msg when doing challenge response for :"+\
                        str(node_name) +\
                        " the message was :" + str(msg))
                
            except zmq.ZMQError as e:
                
                if e.errno == zmq.EAGAIN:
                    
                    pass
                
                # This code is disabled for now, but leaving it here as a warning to 
                # all that might use it, it seems to hang the thread/process in 
                # some cases and I'd recommend  you not use it unless you're desperate :S
                elif e.errno == zmq.EHOSTUNREACH:
                    self.logger.error("CRFileRequest.challenge_resp" + l_sep +\
                        " Host Unreachable for :" + str(router_id))
                        
                
            except AssertionError:
                
                raise
            
            time_left = self.timeout - (time.time() - start_time)  
        
        return ret
        
    def add_recv_task(self, task):
        """ Adds an asynchronous task to the task list
        
        Arguments: 
            task:   pydict: {'action'   :function - function to constantly run while 
                                        task is alive.
                            'timeouts'  : pydict  - collection of timeouts
                                timemout = {'start_time':float - time given 
                                                                by perf_counter
                                            'duration': float - length of timeout in secs
                                            'timeout_func': function - function to run
                                                                    when out of time
                                            'timeout_args': pytuple - args and kwargs
                                                            for timeout func
                                                (timeout_args = (args: pylist - list of 
                                                                                args
                                                            kwargs: pydict - dict of 
                                                                                kwargs
                                                )
                                            }
                                            
                            'handle_recv_data': function - run when there is data from the 
                                                peer to process
                            'complete':         function - run when the file transfer is 
                                                done
                            'cancel':           function - run when the request is
                                                cancelled
                            'data':             pydict - A collection of all data required 
                                                for the recv operation
                            'in_buffer':        pylist - a list of file
                                                data received for this
                                                request and awaiting 
                                                processing by the 
                                                'hanlde_recv_data' func.
                            } 
            
        Returns: 
            req_uuid:   string: unique id for this request
        Side Effects:
            adds a new request task to the list of current request tasks
        Exceptions:
            None
        Description:
            this method adds a new recv file task to the list of current recv tasks in 
            self.recv_tasks. Tasks currently in use are to connect to a node via a 
            challenge/resp task, get file information and to receive file data.
            
            The methods employed are functional in their programming nature and completely
            asynchronous, allowing multiple connects and transfers at the same time 
            without using any blocking calls or multiple threads.
        
        
        """
        
        req_uuid = bytes(str(uuid.uuid4()),"utf-8")
        task[start_time] = time.perf_counter()
        
        self.recv_tasks[req_uuid] = task
        # self.logger.debug("CRMain.add_async_task: " + l_sep +\
#             " A new task was added to the internal async tasks list : " +\
#             str(t_uuid))
        
        return req_uuid
        
    def process_recv_tasks(self):
        """ Process each request to receive a file
        
        Arguments: 
            None:
        Returns: 
            Nothing:
        Side Effects:
            Processes each task in self.recv_tasks which may call their functions as well.
        Exceptions:
            None
        Description:
            
            This method runs the functions from each recv file task to make requests and
            process received file data. It also checks for timed out requests and runs
            the task's timedout handler if they've run out of time.
            
        """ 
        
        tasks = self.recv_tasks.copy() # use a copy so we can remove tasks without 
                                       # raising exceptions.
                                       
        for req_uuid, task in tasks.items():
        
            # call the timeout task if time's up
                                                
            #check if task has incoming data and process
            if task[in_buffer]:
                task[handle_recv_data](req_uuid, task) # may call task complete. 
            
            # otherwise continue to run the task
            task[action](req_uuid, task)
            
                
    def run(self):
        
        self.running = True
        
        log_buffer = []
        
        try:
        
            while self.running:
                
                #__________ Run all current tasks  _____________________________________#
                
                self.process_recv_tasks()
                
                #__________ Check the zmq mailbox! _____________________________________#
                
                events = dict(self.poller.poll(timeout = 5))
                
                # if we've got commands from the main thread, process them
                if self.inproc in events:
                
                
                    json_msg = self.inproc.recv_json()
                
                    msg = MsgWrapper.deserialize(json_msg)
                
                    if msg.command in self.handlers:
                        
                        self.handlers[msg.command](msg)
                        
                        
                # if we have msgs from the client's file server, like data chunks
                # or a challenge resp msg, process them            
                if self.router in events:
                    
                    msg_raw = self.router.recv_multipart()
                    
                    # Send response when challenged by the file server running
                    # on a client. It makes more sense to do it this way, since
                    # the client's file server will connect and then start sending 
                    #msgs to the already listening file requester on the server.
                    
                    if msg_raw[1] == b'HELLO?':
                        self.router.send_multipart(
                            [msg_raw[0], b'HELLO!'])
                        self.logger.debug("CRFileRequest.run:" +l_sep+\
                            "Received HELLO? msg, responding")
                        self.file_server_ready = True
                        
                    # received a file chunk for a request, place it in the appropriate
                    # buffer
                    elif msg_raw[1] == b'HELLO!':
                        pass
                        
                    elif msg_raw[4] in self.recv_tasks:
                        self.recv_tasks[msg_raw[4]][in_buffer].append(msg_raw)
                        
                        
                    else: 
                        #we don't push individual log events to the file, only once t
                        # there's at least a pipeline's worth.
                        if len(log_buffer) < PIPELINE:
                            
                            log_buffer.append("CRFileRequest.run" + l_sep +\
                                "Received msg that didn't have valid "+\
                                "req_uuid or type: " +\
                                
                         str(msg_raw[1]) + ":" + str(msg_raw[2]))
                            
                        else:
                            while log_buffer:
                                log_entry = log_buffer.pop()
                                self.logger.debug(log_entry)
            
        except zmq.ZMQError as e:
        
            #eterm means context is gone, and so are we! Exit
            if e.errno == zmq.ETERM:
            
                self.logger.info("CRFileRequest.run" + l_sep +\
                    "Got ETERM, shutting down.")
        
            else:
            
                location = "CRFileRequest.run"
            
                log_string = "An unexpected zmq error occured."+\
                        " The error was..."
            
                utils.handle_generic_except(location, log_string, self.logger)
                
        except:
            
            location = "CRFileRequest.run"
            
            log_string = "An error occured whilst trying to get a "+\
                " file request and process it. The error was..."
                
            utils.handle_generic_except(location, log_string, self.logger)
        
        ## END OF WHILE LOOP
            
        # exit and clean up
        
        self.router.close(linger = 0)
        self.inproc.close(linger = 0)
        self.poller.unregister(self.router)
        self.poller.unregister(self.inproc) 
        self.temp_dir.cleanup()
        
        self.logger.info("CRFileRequest.run:" +l_sep+\
            "file requester shutting down..")
        
        
    def exit(self, msg):
        
        self.logger.info("CRFileRequest.exit: " + l_sep +\
            "exited due to an unexpected command :" + str(msg.attributes))
        
        
        self.running = False
            
            
    def update_timeout_prefs(self, msg):
        
        self.timeout = msg.attributes[utils.timeout]
            
        self.logger.info("CRFileRequest.inproc_handlers:" + l_sep +\
                "updated network timeout, now using :" +\
                str(self.timeout) + " seconds.")
                
    def connect_node(self, msg):
        """ connects the file server to a render node
        this method connects the file server to a render node using the address given
        in the msg argument. The msg argument needs to be a utils.MsgWrapper object
        with an attribute called utils.server_endpoint which stores the endpoint that
        the files server connects to as a string in the following format:
        
            '0.0.0.0:00000' 
            
        This is then used to connect to the render node. The zmq socket that is 
        used is of the ROUTER type and is connected to multiple render nodes, each 
        endpoint is stored in a list.
        
        """
        
        node_endpoints = msg.attributes[utils.server_endpoint]
        node_router_id = msg.attributes[utils.requesting_id]
        
        for endpoint in node_endpoints:
            
        
            if endpoint[address] in self.render_node_eps:
            
                #this is just a check to alert us to the fact we're attempting to connect
                # to a node we've already connected to. nothing more, nothing less :D
            
                self.logger.info("CRFileRequest.connect_node:" +l_sep+\
                    " already connected to this node: " +\
                         str(endpoint[address]))
                         
            #Set the peer's public key, this means the peer is acting as a server
            # and has bound its socket, this thread is acting as client and will
            # connect.
            self.router.curve_serverkey = bytes(endpoint[public_key], 'utf-8')
            
            self.router.setsockopt(zmq.LINGER, 0)             
            self.router.connect(endpoint[address])
                
            
                
            # see if the node is actually listening now.
            if self.challenge_resp(node_router_id, msg, endpoint[address]):
        
                self.render_node_eps.append(endpoint)
                self.logger.info("CRFileRequest.connect_node:" +l_sep+\
                    " connected to: " + str(endpoint[address]))
        
            else:
                # if we timeout we just disconnect from the endpoint and assume
                # its dead. 
                disconnect_msg = MsgWrapper(command = utils.disconnect,
                    attributes = {utils.server_endpoint:[endpoint[address]]})
                
                self.disconnect_node(disconnect_msg) 
        
                self.logger.warning("CRFileRequest.connect_node:" +l_sep+\
                    " could not establish comms for : " +\
                            str(endpoint) + " so it was disconnected")
                conn_failed = MsgWrapper(message = utils.connect_failed,
                    s_uuid = msg.s_uuid,
                    attributes = {
                        utils.node_name:msg.attributes[utils.node_name],
                        utils.node_address:endpoint[address].split(":")[0]})
                    
                self.inproc.send_json(conn_failed.serialize())
                #TODO - what if the challenge times out, what do we do then?
    
    def file_transf_req(self, msg):
        
        """ Create a new request to get file info and then get the file
        
        Arguments:
            msg:        utils.MsgWrapper - CR message object which must contain.
                s_uuid:     string -    unique id of the requesting peer session
                t_uuid:     string -    Optional, unique id of the task requesting this 
                    file.
                    
                attributes = {
                    fid             string      - file path I am requesting
                    file_path       string      - where I will put this new file
                    func            string      - what handler to run after complete
                    msg_attributes  dictionary  - arguments for the handler if any
                    router_id       bytes       - zmq identity of the peer to request from
                    } 
            
        Returns:
            nothing
        Side Effects:   
            Requests the file information from a peer, on success, adds a file request
            task to the list of current tasks. If the task fails, sends a msg to the 
            ulimate recipient of the task.
        Exceptions:
            None        
        Description:
        """
        

        ## GET PROPERTIES OF THE FILE REQUEST
              
        fid = msg.attributes[utils.file_path][0]
        file_path = msg.attributes[utils.file_path][1]
        func = msg.attributes[utils.command]
        msg_attributes = msg.attributes
        router_id = msg.attributes[utils.node_uuid]
        t_uuid = msg.t_uuid    
        s_uuid = msg.s_uuid
        
        
       
        dynamic_timeout_max = 30.0 # start with 30s, if we get timeouts, increase


        
        file_req_data = {   
            file_id                 :fid,
            all_offsets             :[],
            offsets                 :[],
            f_write_to              :file_path,
            msg_attribs             :msg.attributes,
            peer_id                 :router_id,
            task_id                 :t_uuid,
            session_id              :s_uuid,
            round_trip_time         :[],
            file_total_rcvd         :0,
            chunks_rcvd             :0,
            f_size                  :0,
            req_start_time          :0.0,
            req_to_duration         :5.0,
            max_to_duration         :30,
            temp_file               :os.path.join(self.temp_dir.name, 
                                                s_uuid.decode('utf-8') +\
                                                 "_" +\
                                                os.path.basename(file_path)
                                                )
                                    
                                                # temp_file will be a temp location, 
                                                # consisting of a folder in the OS's 
                                                # temp dir with name of the sess_uuid
                                                # and the file name desired to be written
                                                # to. Kinda avoids trouble this way.
                        
                        
                        }
                            
        
        ## CREATE THE REQUEST TASK STRUCTURE
        
        task = {
                action                  :self.request_file_info,
                handle_recv_data        :self.handle_rcvd_file_info,
                complete                :self.file_info_recv_complete,
                cancel                  :self.cancel_file_info_req,
                data                    :file_req_data,
                in_buffer               :[]
                
                }
                
        self.add_recv_task(task)
        self.logger.info("CRFileRequest.file_request_req; Created file request for:" +\
                         str(file_id))
        
    def cancel_all_tasks(self, msg):
        """ 
        Arguments:
                             
        Returns:
            nothing
        Side Effects:   
            Cancels any tasks that are currently being processed.
        Exceptions:
            None        
        Description:
            Cancels any tasks that are currently in the tasks list
        """
        tasks = self.recv_tasks.copy()
        
        for req_uuid, tsk in tasks.items():
            
            tsk[cancel](req_uuid, tsk)
            
        self.logger.debug("CRFileRequest.cancel_all_tasks" + l_sep +\
            "Cancelled all tasks")      

        
    def request_file_info(self, req_uuid, task):
        """ Sends a request for file info to the peer given in the task argument
        
        Arguments:
            req_uuid    - string    - the unique request id associated with this request
            task        - dict      - the task data for this request
            
                                        
        Returns:
            nothing
        Side Effects:   
            Requests the file information from a peer, on success, adds a file request
            task to the list of current tasks. If the task fails, sends a msg to the 
            ulimate recipient of the task.
        Exceptions:
            None        
        Description:
            Requests file information such as file size from the peer which has the file.
            If the request succeeds, this function will create a new task to request the
            file in chunks from the peer. If the request fails, then a msg will be sent 
            to the original requesting party of the task to get the file telling it the
            transfer did not work. 
            There are no retries, its up to the original reqeuster to handle a failure
            and retry the transfer, this could be a managing function/object or ultimately
            the user.        
        
        
        """
        
        ## CHECK TIMEOUTS AND SEND REQ IF REQURED
        
        if task[data][req_start_time] == 0.0:
            task[data][req_start_time] = task[start_time]
            
            #send request for file info
            info_request = [bytes(task[data][peer_id], 'utf-8'),
                            b"FILE_INFO",
                            bytes(task[data][file_id], 'utf-8'),
                            b'',
                            req_uuid
                            ]
                        
        
            self.router.send_multipart(info_request)
            
        elif timed_out(task[data][req_start_time], task[data][req_to_duration]):  
            
            info_request = [bytes(task[data][peer_id], 'utf-8'),
                            b"FILE_INFO",
                            bytes(task[data][file_id], 'utf-8'),
                            b'',
                            req_uuid
                            ]
                            
            self.router.send_multipart(info_request)
            
            task[data][req_start_time] = time.perf_counter()
            
            
        if timed_out(task[data][req_start_time], task[data][max_to_duration]):
        
        ## REQUEST FAILED, NOTIFY CALLER
        
            recv_fail_msg = MsgWrapper(message = utils.recv_fail,
                t_uuid = task[data][task_id],
                s_uuid = task[data][session_id],
                attributes = {utils.file_path:task[data][f_write_to]})
                        
            self.logger.warning(
                "CRFileRequester.request_file_info; Failed to retrieve "+\
                "file info for transfer of: " + str(task[data][file_id]))
            
            self.inproc.send_json(recv_fail_msg.serialize())
            self.recv_tasks.pop(req_uuid)
    
    
    def handle_rcvd_file_info(self, req_uuid, task):
        """ Handle data received from a request for file info
        
        Arguments:
            req_uuid    - string    - the unique request id associated with this request
            task        - dict      - the task data for this request
                                        
        Returns:
            nothing
        Side Effects:   
            Processes file information and then calls the complete function for the
            associated request.
        Exceptions:
            None        
        Description:
            
        
        """  
        
        file_size = 0
        buff_pop = task[in_buffer].pop
        
        ## GET FILE INFO
        while task[in_buffer]:
            
            msg = buff_pop()
            
            assert msg[1] == b'FILE_INFO'
            
            assert msg[4] == req_uuid
            
            file_size = int.from_bytes(msg[3], byteorder='big', signed=False)
            
            continue
            
        # if we did get the file_size data, then complete this task
        if file_size and not msg[1]==ERROR:
            
            task[data][round_trip_time].append(
                time.perf_counter() - task[data][req_start_time]
                                                )
            task[data][req_start_time] = time.perf_counter()
            task[data][all_offsets] = [i * CHUNK_SIZE \
                for i in range(0, ceil(file_size / CHUNK_SIZE)) ]
            
            task[data][f_size] = file_size
            task[complete](req_uuid, task)
            
            self.logger.info("CRFileRequest.handle_rcvd_file_info; "+\
                                "file size on server is : " +\
                                str(file_size) + " for " +\
                                task[data][file_id])
            
        else:
            
            recv_fail_msg = MsgWrapper(message = utils.recv_fail,
            t_uuid = task[data][task_id],
            s_uuid = task[data][session_id],
            attributes = {utils.file_path:task[data][f_write_to]})
                
            self.inproc.send_json(recv_fail_msg.serialize())
            
            self.logger.warning("CRFileRequest.handle_rcvd_file_info; "+\
                                "No file size data received for : " +\
                                task[data][file_id])
        
        
    def file_info_recv_complete(self, req_uuid, task):
        """ Completes and removes a request for file info, creates a new file request
        """
        
        ## CREATE FILE TRANSFER REQUEST
        dynamic_timeout_max = 30.0 # start with 30s, if we get timeouts, increase
        if (os.path.exists(task[data][temp_file])) :
            os.remove(task[data][temp_file])#TODO: Will cause winerr 32 for multiple
                                            # file requests of the same file (user button
                                            # bashes the "resync" button
                                            
            msg_str = ("CRFileRequest.file_info_recv_complete:" + l_sep + \
                "Deleting file : " + task[data][f_write_to])
            self.logger.info(msg_str)
            
         #NOTE: open mode must not have 'a' in its string as this mode
            # will ignore seeks on windows, possibly unix as well.    
        file = open(task[data][temp_file], "wb")
        
        file_req_data = {   
            file_id                 :task[data][file_id],
            all_offsets             :task[data][all_offsets],
            offsets                 :[],
            f_write_to              :task[data][f_write_to],
            msg_attribs             :task[data][msg_attribs],
            peer_id                 :task[data][peer_id],
            task_id                 :task[data][task_id],
            session_id              :task[data][session_id],
            f_handle                :file,
            f_size                  :task[data][f_size],
            round_trip_time         :task[data][round_trip_time],
            file_total_rcvd         :0,
            chunks_rcvd             :0,
            req_start_time          :0.0,
            req_to_duration         :30.0,
            max_to_duration         :30.0,
            temp_file               :task[data][temp_file],
            'doubles'               :{},
            'bad_hash_chunks'       :{},
            timeout_retries         :TIMEOUT_RETRIES
            
            }
                            
        
        ## CREATE THE FILE REQUEST TASK STRUCTURE
        
        task = {
            action                  :self.request_file_data,
            handle_recv_data        :self.handle_rcvd_data,
            complete                :self.file_recv_complete,
            cancel                  :self.cancel_file_recv,
            data                    :file_req_data,
            in_buffer               :[]
            
            }
            
        ## ADD THE FILE REQUEST TASK 
        self.add_recv_task(task)
        
        self.recv_tasks.pop(req_uuid)
        
    def cancel_file_info_req(self, req_uuid, task):
        """ Cancels a request to get file info
        """
        
        self.logger.info("CRFileRequest.cancel_file_info_req" + l_sep+\
            "cancelling file info request for :" + task[data][file_id])
        
        self.recv_tasks.pop(req_uuid)
        
        
    def request_file_data(self, req_uuid, task):
        """ Request file chunks 
        
        Arguments:
            req_uuid    - string    - the unique request id associated with this request
            task        - dict      - the task data for this request
        Returns:
            nothing
        Side Effects:   
            Sends a request for file data to the connected peer identified in the task
        Exceptions:
            None        
        Description:
            Makes a file request and sends it to the peer identified in the data section
            of the task object. 
            
            """                
        
        offs_append = task[data][offsets].append
        offs_reverse= task[data][offsets].reverse
        offs_copy = task[data][offsets].copy
        
        new_offs_req = []
        new_offs_req_app = new_offs_req.append
        
        
        file = task[data][f_handle]
        
        ## CHECK OUTSTANDING OFFSETS
        # If there are outstanding offsets, then exit early and wait for them 
        # to arrives
        
        if task[data][req_start_time] == 0.0:
            task[data][req_start_time] = task[start_time]
        
        if not task[data][offsets] or\
            timed_out(task[data][req_start_time], task[data][req_to_duration]):
           
            all_offs_pop = task[data][all_offsets].pop
            router_id = task[data][peer_id]
            fid = task[data][file_id]
            s_uuid = task[data][session_id]
            r_trip_time = task[data][round_trip_time]
            offsets_requested = []
            offsets_requested_append = offsets_requested.append
            
            credit = min(PIPELINE, len(task[data][all_offsets]))
            
            while credit > 0:
                
                offset = all_offs_pop()
                
                # append both the required offset and chunk size
                # Add to the list we'll actually send, we do re-request 
                # offsets that are already in [data][offsets] just
                # in case their packet got dropped. Not doing this
                # risks that the offset would never be re-requested and the
                # file transfer could never finish.
                offsets_requested_append([offset, CHUNK_SIZE])
                
                # Add to the list of offsets we've requested just for this
                # request
                new_offs_req_app(offset)
                
                #don't add offsets to the list we're currently requesting, if 
                # they are already on it. It makes the list grow and we 
                # request more data than we need to, in extreme cases the 
                # file transfer progress can go backwards.
                if not offset in task[data][offsets]:
                
                    # Add to the list of offsets we're tracking as requested
                    offs_append(offset)
                
                
                credit -= 1
            
            request = [
                bytes(router_id, 'utf-8'),
                b'FILE_DATA',
                bytes(fid, 'utf-8'),                
                pickle.dumps(offsets_requested),
                req_uuid,
                ]
            
            self.router.send_multipart(request)
            
            
            ## PUT REQUESTED CHUNKS TO END OF LIST
            # This gives any delayed chunks a chance to arrive later on 
            # without requesting them repeatedly extending our timeout
            
            new_offs_req.reverse()
            temp_offsets = new_offs_req.copy()
            temp_offsets.extend(task[data][all_offsets])
            task[data][all_offsets] = temp_offsets.copy()
            
            #set timeout durations for this task
            if len(r_trip_time) > 2:
                
                # Set the timeout to the mean plus 2 stdevs to cover 97% of 
                # round trip times
                dynamic_timeout =  mean(r_trip_time) + 6 * stdev(r_trip_time)
                
                task[data][req_to_duration] = dynamic_timeout
                
            elif r_trip_time:
            
                dynamic_timeout =  10#5 * max(r_trip_time) 
                
                task[data][req_to_duration] = dynamic_timeout
                
            else:
            
                task[data][req_start_time] = task[start_time]
                 
            
        if timed_out(task[data][req_start_time], task[data][max_to_duration]):
            
            
            if task[data][timeout_retries]:
                task[data][timeout_retries] -= 1
            
                task[data][req_start_time] = time.perf_counter()
                self.logger.warning("Timed out with " +\
                    str(task[data][timeout_retries]) + \
                    " tries left while receiving "+\
                    task[data][f_write_to])
                
            else:
            ## REQUEST FAILED, NOTIFY CALLER
                recv_fail_msg = MsgWrapper(message = utils.recv_fail,
                    t_uuid = task[data][task_id],
                    s_uuid = task[data][session_id],
                    attributes = {utils.file_path:task[data][f_write_to]})
                
                self.logger.warning(
                    "Receiving data timed out for " +\
                    task[data][file_id] +\
                    ", doubled chunks: " + str(task[data]['doubles']) +\
                    ", chunks not transferred: " +\
                     str(len(task[data][all_offsets])) +\
                    " out of " + str(task[data][f_size] / CHUNK_SIZE) ) 
                    
                    
                self.inproc.send_json(recv_fail_msg.serialize())
                
                #remove this task
                self.recv_tasks.pop(req_uuid)
                
                
        else:
            pass
        
    def handle_rcvd_data(self, req_uuid, task):
        """
        Arguments:
            req_uuid    - string    - the unique request id associated with this request
            task        - dict      - the task data for this request
        Returns:
            nothing
        Side Effects:   
            Handles a response to a request for file data to the connected 
            peer identified in the task
        Exceptions:
            None        
        Description:
        """ 
        loads = pickle.loads
        perf_counter = time.perf_counter
        
        file = task[data][f_handle]
        f_seek = file.seek
        f_write = file.write
        
        round_trip = []
        file_size = task[data][f_size]
        r_trip_time_append = task[data][round_trip_time].append
        router_id = task[data][peer_id]
        t_uuid = task[data][task_id]
        s_uuid = task[data][session_id]
        buff_pop = task[in_buffer].pop
        
        
        rt_append = round_trip.append
        off_req_remove = task[data][offsets].remove
        all_off_req_remove = task[data][all_offsets].remove
        
        
        while task[in_buffer]:
            
            msg = buff_pop()
            
            identity, command, bfid, boffset, req_uuid, f_data, bhash = msg
            
            rcvd_offset = loads(boffset)
            
            if not hash_algorithm(f_data).digest() == bhash:
                
                if rcvd_offset in task[data]['bad_hash_chunks']:
                
                    task[data]['bad_hash_chunks'][rcvd_offset] += 1
                    
                else:
                    
                    task[data]['bad_hash_chunks'][rcvd_offset] = 1
                
                self.logger.warning("CRFileRequest.handle_rcvd_data:" +\
                    "chunk failed hash check, this chunk will be rejected."+\
                    " This chunk (" + str(rcvd_offset) + " failed "+\
                    str(task[data]['bad_hash_chunks'][rcvd_offset]) + \
                    " times, it was :" + str(sys.getsizeof(f_data)))
                    
                
            else:
                
                
                
                f_seek(rcvd_offset, SEEK_SET)
                f_write(f_data)
                
                #Where a chunk gets delayed and gets received along with another 
                # block, there's a risk we might try to remove the associated
                # offset twice. We mitigate that risk here by checking first.
                if not rcvd_offset in task[data][all_offsets]:
                    
                    if rcvd_offset in task[data]['doubles']:
                        task[data]['doubles'][rcvd_offset] += 1
                    else:
                        task[data]['doubles'][rcvd_offset] = 1
                    
                else:
                    all_off_req_remove(rcvd_offset)
                    
                if not rcvd_offset in task[data][offsets]:
                    
                    pass
                    
                else:
                    # to get the correct round trip time, we need to take the
                    # time from the request to the first packet that was part
                    # of that request. Then use this to calculate the right 
                    # amount of time to wait for the subsequent packets
                    rt_append(perf_counter() - task[data][req_start_time])
                    
                    off_req_remove(rcvd_offset)
                    
                task[data][chunks_rcvd] += 1
                size = len(f_data)
                task[data][file_total_rcvd] += size
                
                task[data][req_start_time] = time.perf_counter()
            
            
        if round_trip:
            r_trip_time_append(round_trip[0]) #only care about the first one recvd 
                                                # the rest aren't really round trips
                                                # since they're measured from the last
                                                # received chunk, not the rquest that
                                                # caused them.
                
                #notify the user of the total file progress actually received
        recv_prog = \
        max( (1 - len(task[data][all_offsets]) * CHUNK_SIZE / file_size) * 100, 
                0
            )
        
        
        # update the user on progress using actual bytes received    
        prog_msg = MsgWrapper(message = utils.progress_update,
                t_uuid = t_uuid,
                s_uuid = s_uuid,
                attributes = {utils.percent_complete:recv_prog,
                            utils.node_uuid:router_id,
                            utils.status:utils.downloading_results
                })
                
        #TODO: Really need to have a system for response/status codes coming back from
        # render nodes. The current system is pretty hap hazard and prone to a lot of
        # hacks to get it to work properly. In this instance, its incorrect to have the
        # status set to downloading. This code has no idea why its transferring a file
        # so it certainly shouldn't be claiming to put the node into this state.
                    
        self.inproc.send_json(prog_msg.serialize())
        
            
        if not task[data][all_offsets]:
            #we're finished then, call complete so we can end this task
            task[complete](req_uuid, task)
            self.logger.info("CRFileRequest.handle_rcvd_data:" + l_sep +\
                "Blocks with duplicated chunk requests: " +\
                 str(task[data]['doubles']))
            
    def file_recv_complete(self, req_uuid, task):
        """ completes a rcv file task and removes it from the list of tasks
        
        Arguments:
            req_uuid    - string    - the unique request id associated with this request
            task        - dict      - the task data for this request
        Returns:
            nothing
        Side Effects:   
            Completes a request for file data to the connected peer identified in the task
        Exceptions:
            None        
        Description:
            
        """
        
        r_trip_time = task[data][round_trip_time]
        t_uuid = task[data][task_id]
        msg_attributes = task[data][msg_attribs]
        file = task[data][f_handle]
        fid = task[data][file_id]
        chunks = task[data][chunks_rcvd]
        total = task[data][file_total_rcvd]
        
        ## STATS FOR TRANSFER
        # Calculate and log stats for this transfer                    
        mean_trip = mean(r_trip_time)
        if len(r_trip_time) > 2:
            stdev_trip = stdev(r_trip_time)
        else:
            stdev_trip = 0.0
    
        msg_str = ("CRFileRequest.file_recv_complete:" +l_sep+\
            "file %s :  %i chunks received, %i bytes" %
                 (fid, chunks, total))
        
        stats = ("CRFileRequest.file_recv_complete:" +l_sep+\
                "file " + fid  + l_sep + str(mean_trip) +\
                l_sep + "seconds mean round trip time" +\
                l_sep + str(stdev_trip) + l_sep + " seconds std deviation " 
                )
                
             
        self.logger.info(msg_str)
        self.logger.info(stats)
        
        ## CLOSE FILE HANDLE
        file.close()
        
        ## COPY TEMP FILE 
        shutil.copy2(task[data][temp_file], task[data][f_write_to])
        
        ## SEND FINISHED MSG
        msg_attributes[utils.status]= utils.ready
        finish_msg = MsgWrapper(
            command = msg_attributes[utils.command],
            t_uuid = t_uuid,
            attributes = msg_attributes)
    
        self.inproc.send_json(finish_msg.serialize())
                        
        #task done so remove it from the list
        self.recv_tasks.pop(req_uuid)    
        
    def cancel_file_recv(self, req_uuid, task):
        """ Cancels a task to recv a file
        
        Arguments:
            req_uuid    - string    - the unique request id associated with this request
            task        - dict      - the task data for this request
        Returns:
            nothing
        Side Effects:   
            Cancels a request for file data to the connected peer identified in the task
        Exceptions:
            None        
        Description:
        """
        r_trip_time = task[data][round_trip_time]
        t_uuid = task[data][task_id]
        msg_attributes = task[data][msg_attribs]
        file = task[data][f_handle]
        fid = task[data][file_id]
        chunks = task[data][chunks_rcvd]
        total = task[data][file_total_rcvd]
        
        ## STATS FOR TRANSFER
        # Calculate and log stats for this transfer                    
        mean_trip = mean(r_trip_time)
        if len(r_trip_time) > 2:
            stdev_trip = stdev(r_trip_time)
        else:
            stdev_trip = 0.0
    
        msg_str = ("CRFileRequest.cancel_recv:" +l_sep+\
            "Transfer was cancelled. " +\
            "file %s :  %i chunks received, %i bytes" %
                 (fid, chunks, total))
        
        stats = ("CRFileRequest.cancel_recv:" +l_sep+\
                "file " + fid  + l_sep + str(mean_trip) +\
                l_sep + "seconds mean round trip time" +\
                l_sep + str(stdev_trip) + l_sep + " seconds std deviation " 
                )
                
             
        self.logger.debug(msg_str)
        self.logger.info(stats)
        
        msg_attributes[utils.status]= utils.ready
        
        finish_msg = MsgWrapper(
            command = msg_attributes.get(utils.cancelled_command),
                t_uuid = t_uuid,
                attributes = msg_attributes)
    
        self.inproc.send_json(finish_msg.serialize())                
            
        file.close() 
        
        self.recv_tasks.pop(req_uuid)
        
        
def discover_local_ip():

    import socket, subprocess, platform
    #names_addrs = (('',), ('',), ('',))
    
    address_list = ()
    
    #get host names and ip addresses
    if platform.system() == 'Windows':
    
        try:
            names_addrs = socket.gethostbyname_ex(socket.gethostname())
        
            addresses = names_addrs[2]
        
            for address in addresses:
                address_list += (
                    (address,
                    address,
                    "address of your network device for this computer"
                    ),
                    )
        
        except:
            
            address_list  += (
                (
                '0.0.0.0',
                '??',
                "address of this computer on the network",
                ),
                )
                            
    elif platform.system() == 'Linux':
        
        import subprocess
        
        try:
            
            names_addrs = socket.gethostbyname_ex(
                socket.gethostname() + ".local")
            
            addresses = names_addrs[2]
        
            for address in addresses:
                address_list += (
                    (address,
                    address,
                    "address of your network device for this computer"
                    ),
                    )                
            
        
        except:
            
            address_list  += (
                (
                '0.0.0.0',
                '??',
                "address of this computer on the network",
                ),
                )
        
        
    
    elif platform.system() == 'Darwin':
    
        output = subprocess.check_output(
            "networksetup -listallhardwareports", shell=True)
        
        output = output.decode()
        
        lines = output.splitlines()
        
        #print(lines)
        
        interfaces = {}
        interface_name =''
        
        for line in lines:
            if line.startswith('Hardware Port'):
                title, interface_name = line.split(": ")
                interfaces[interface_name] = list()
                interfaces[interface_name].append(interface_name)
                
            elif line.startswith('Device'):
                if not interface_name == '':
                    device, device_name = line.split(": ")
                    interfaces[interface_name].append(device_name)
                    
        for interface_name, device_data in interfaces.items():
            
            try:
                ipaddr_raw_output = subprocess.check_output(
                    "ipconfig getifaddr " + \
                    device_data[DEVICE_NAME], shell=True)
                #print(ipaddr_raw_output)
                ipaddr_string = ipaddr_raw_output.decode()
                ipaddr_string = ipaddr_string.rstrip("\n")
                interfaces[interface_name].append(ipaddr_string)
            except:
                
                print("couldn't get address for device ", 
                      device_data[DEVICE_NAME])
        
            #now get the list of all ip addresses currently bound to this
            # machine, note, if the machine connects to the internet, one 
            # of these addresses will correspond to the modem device, but 
            # won't necessarily be the public ip of the internet connection.
        
        
        for interface in interfaces.values():
        
            try:
                address_list += (
                            (interface[IF_IPADDR],
                            interface[HARDWARE_PORT_NAME] + "  (" + \
                                    interface[IF_IPADDR] + ")",
                            interface[DEVICE_NAME],
                            ),
                            )
            except:
                address_list += (
                                ('', '' + "  (" + \
                                    '' + ")",
                            '',
                            ),
                            )
                
                
                print("interface ", interface[HARDWARE_PORT_NAME], 
                    " is not connected")

    # Pick the first available address for the client machine,
    # TODO:JIRA:CR-38 Add a button that can access this code and run it again 
    # in case the user adds a connection and wants to use it without
    # shutting down blender.
    
        
    print(address_list)

    return address_list        
        
#========================== END OF discover_local_ip =====================================      

