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
utils - utility functions

Purpose

How

Classes Exported - 

Errors Raised - None (as yet)

Functions Exported - None

"""

####
### Helper module for example applications. Mimics ZeroMQ Guide's zhelpers.h. 
#### 
from __future__ import print_function 

import binascii, logging, os, sys, uuid, requests, pathlib
import zmq, cProfile, platform, tempfile
import time, json, sys, bpy, threading

import distro
from mathutils import Vector, Quaternion, Euler, Color
from . import config
from . import logging as CRLogging
from . config import read_config_file, write_config_file
from . logging import l_sep
#Convention for string constants, COMMANDS, data (just in case you didn't catch that
# upper case is for commands or messages used in directing msgs to handlers, lower
# case is for data labels or dictionary keys.



crowdrender = sys.modules[__package__]

process = crowdrender.process
cr_build_type = crowdrender.cr_build_type
cr_build_branch = crowdrender.cr_build_branch
cr_version = crowdrender.cr_version


### SHARED DEFS 

previously_selected_int = -2
last = -1
dictionary = 1
list_selected = 0
output_buffer_size = 30
address = 0
public_key = 1



### COMMANDS
data_update = 'DATA_UPDATE'
disconnect = 'DISCONNECT'
discovery_login = 'DISCOVERY_LOGIN'
discovery_refresh = 'DISCOVERY_REFRESH'
discovery_refresh_rental = 'DISCOVERY_REFRESH_RENTAL'
discovery_request_rental = 'DISCOVERY_REQUEST_RENTAL'
cancel = 'CANCEL'
cancelled_command = 'CANCELLED_COMMAND'
connect_node = 'CONNECT_NODE'
connection_req = 'CONNECTION_REQUEST'
cancel_connection = 'CANCEL_CONNECTION'
cancel_render = 'CANCEL_RENDER'
change_num_instances = 'CHANGE_NUM_INSTANCES'
exit = 'EXIT'
start_server_session = 'START SESSION'
run_unit_tests = 'RUN_UNIT_TESTS'
local_address_update = 'LOCAL_ADDRESS_UPDATE'
login_cloud = 'LOGIN_CLOUD'
logout = 'LOGOUT'
server_address_update = 'SERVER_ADDRESS_UPDATE'
client_address_update = 'CLIENT_ADDRESS_UPDATE'
server_port_update = 'SERVER_PORT_UPDATE'
server_connect = 'SERVER_CONNECT'
start_rental_request = 'START_RENTAL_REQUEST'
stop_rental_request = 'STOP_RENTAL_REQUEST'
image_request = 'IMAGE_REQUEST'
render = 'RENDER'
make_hash_tree = 'MAKE_HASH_TREE'
file_transf_req = 'FILE_TRANSF_REQ'
cip_alive = 'cip_alive'
sip_alive = 'sip_alive'
init_addrs = 'INITIALISE_ADDRESSES'
init_session = 'INITIALISE_SESSION'
update_client_screen = 'UPDATE_CLIENT_SCREEN'
render_eng_update = 'RENDER_ENG_UPDATE'
finalise_render = 'FINALISE_RENDER'
result_coords = 'RESULT_COORDS'
get_nodes_by_uuid = 'GET_NODES_BY_UUID'
get_node_attrib_hashes = 'GET_NODE_ATTRIB_HASHES'
update_timeout_prefs = 'UPDATE_TIMEOUT_PREFS'
update_node_status = 'UPDATE_NODE_STATUS'



### ATTRIBUTE DATA

active_mat_ind = 'active_mat_ind'
active_mat_slot = 'active_mat_slot'
attributes = 'attributes'
attribute_hashes = 'attribute_hashes'
attribute_hash = 'attribute_hash'
cancel_upload = 'cancel_upload'
cancel_tile_download = 'cancel_tile_download'
client_address = 'client_address'
client_uuid = 'client_uuid'
client_m_uuid = 'utils.client_m_uuid'
command = 'command'
compute_devices = 'compute_devices'
compute_device = 'compute_device'
connect_failed = 'connect_failed'
connect_error = 'connect_error'
coords = 'coords'
creds = 'creds'
crowdrender_session_metadata = '.crowdrender_session_metadata'
current_frame = 'current_frame'
duplicated_nodes = 'duplicated_nodes'
endpoint = 'endpoint'
eng_samples = 'eng_samples'
errors= 'errors'
error_message = 'error_message'
enable_nodes = 'enable_nodes'
exr_codec ='exr_codec'
ext_report = 'ext_report'
failed = 'failed'
file_path = 'file_path'
file_received = 'file_received'
file_requester_ep = 'file_requester_ep'
file_server_ep = 'file_server_ep'
file_server_addr = 'file_server_addr'
file_server_down = 'file_server_down'
finished_frame = 'finished_frame'
finished_tile = 'finished_tile'
finished_view = 'finished_view'
frame_range = 'frame_range'
headers = 'headers'
frame_task_uuid = 'frame_task_uuid'
hello = 'hello'
hello_cip = 'hello_cip'
hello_sip = 'hello_sip'
hello_ssp = 'hello_ssp'
http_request = 'http_request'
http_request_type = 'http_request_type'
image_file_path = 'image_file_path'
img_output_fmt = 'OPEN_EXR_MULTILAYER'#'EXR'#'MULTILAYER' #, off limits until 
# https://developer.blender.org/T21410 is solved
image_fmt_selected = 'image_fmt_selected'
is_animation = 'is_animation'
k = 'k'
last_render_time = 'last_render_time'
last_draw_time = 'last_draw_time'
last_setup_time = 'last_setup_time'
load_trusted = 'load_trusted'
local_address = 'local_address'
location = 'location'
manual_loadb = 'manual_loadb'
message = 'message'
message_type = 'message_type'
message_uuid = 'message_uuid'
machine_uuid = 'machine_uuid'
machine_cores = 'machine_cores'
machines_finished = 'machines_finished'
missing_block = 'missing_block'
network_timeout = 'network_timeout'
new_uuid = 'new_uuid'
nodes = 'nodes'
node_A_auto = "node_A_auto"
node_A_manual_values = "node_A_manual_values"
node_uuid = 'node_uuid'
nodes_by_uuid = 'nodes_by_uuid'
node_access_key = 'node_access_key'
node_address = 'node_address'
node_name = 'node_name'
node_prog_stats_endpoint = 'node_prog_stats_endpoint'
num_instances = 'num_instances'
open_blend_file = 'open_blend_file'
operator = 'operator'
on_complete = 'on_complete'
parent_node_uuid = 'parent_node_uuid'
payload = 'payload'
percent_complete = 'percent complete'
persistent_images = 'persistent_images'
process_threads = 'process_threads'
progress_tiles = 'progress_tiles'
progress_update = 'progress_update'
previously_selected = 'previously_selected'
recv_fail = 'recv_fail'
render_complete = 'render_complete'
render_cancelled = 'render_cancelled'
render_engine_ready = 'render_engine_ready'
render_failed = 'render_failed'
render_finished = 'render_finished'
render_nodes = 'render_nodes'
render_job_id = 'render_job_id'
render_stats = 'render_stats'
render_layer_name = 'render_layer_name'
render_pass_name = 'render_pass_name'
repair_attr = 'repair_attr'
repair_item = 'repair_item'
repair_message = 'repair_message'
request = 'request'
requesting_id = 'requesting_id'
request_response = 'request_response'
req_timed_out = "request timed out!"
resolution_x = 'resolution_x'
resolution_y = 'resolution_y'
resolution_percent = 'resolution_percent'
response_data = 'response_data'
result_ready = 'result_ready'
resync = 'resync'
render_engine = 'render_engine'
resync = 'resync'
retry = 'retry'
requesting = 'requesting'
rotation = 'rotation'
router_id = 'router_id'
scale = 'scale'
scene = 'scene'
scene_add_type = 'scene_add_type'
session_path = 'session_path'
selected = 'selected'
access_key= 'access_key'
screen_coords = 'screen_coords' 
screen_res = 'screen_res'
screen_size = 'screen_size'
second_last_uuid = 'second_last_uuid'
server_address = 'server_address'
server_endpoint = 'server_endpoint'
server_error = 'server_error'
server_port = 'server_port'
session_token = 'session_token'
session_uuid = 'session_uuid'
set_enabled_state = 'set_enabled_state'
show_req_notification = 'show_req_notification'
ssp_alive = 'ssp_alive'
status = 'status'
state = 'state'
status_update = 'status_update'
sync_manifest = 'sync_manifest'
tile_x = 'tile_x'
tile_y = 'tile_y'
tiles = 'tiles'
tile_request = 'tile_request'
timeout = 'timeout'
transform_vector = 'transform_vector'
trying_again = 'trying_again'
top_hash = 'top_hash'
t_s = 't_s'
update_render_stats = 'update_render_stats'
update_tile_size = 'update_tile_size'
upload_task_uuid ='upload_task_uuid'
upload_task = 'upload_task'
upload_task_begin = 'upload_task_begin'
upload_task_complete = 'upload_task_complete'
use_nodes = 'use_nodes'
user_blend_file = 'user_blend_file'
user_engine = 'user_engine'
user_file_path= 'user_file_path'
_uuid = 'uuid'
value = 'value'
view_ready = 'view_ready'
view = 'view'
views = 'views'
zmq_error = 'zmq_error'

## DISCOVERY QUERY 

active = 'active'
accessKey = 'accessKey'
auth_required = 'Authorisation Required'
blVersion = 'blVersion'
computerName = 'computerName'
count = 'count'
crVersion = 'crVersion'
error = 'error'
errors = 'errors'
data = 'data'
ip = 'ip'
local = 'local'
logged_in = 'logged_in'
machines = 'machines'
numberOfBlenderGridNodes = 'numberOfBlenderGridNodes'
owner = "owner"
password = 'password'
refreshInterval = 'refreshInterval'
requestRentalInstances = 'requestRentalInstances'
renderCredit = 'renderCredit'
token = 'token'
updateMachine = 'updateMachine'
updateRentalInstanceCount = 'updateRentalInstanceCount'
updateUserCredit = 'updateUserCredit'
url_auth = 'url_auth'
user = 'user'
user_name = 'user_name'
wrong_password = 'Wrong Password'




## STATE CODES
null = 0
ready = 1
syncing = 2
uploading = 3
synced = 4
repairing = 5
rendering = 8
finished_render = 16
frame_finished = 17
finished_composite = 32
render_cancelled = -16
sync_failed = -4
connecting = 64
connected = 128
no_network = -128
connect_failed = -64
cancelling = 255
exited = -1
unresponsive = -2
render_failed = -8
retrying_connect = 65
downloading_results = -3

states = {null:'0:', ready:'1:ready', syncing:'2:syncing', uploading:'3:uploading',
            synced:'4:synced', repairing:'5:repairing',
            rendering:'8:rendering', finished_render:'16:finished render',
            render_cancelled:'-16: render cancelled', 
            frame_finished: '17: frame_finished',
            finished_composite:'32:finished composite', sync_failed:'-4:needs resync',
            connecting:'64:connecting', connected:'128:connected:', 
            no_network:'-128: no network', unresponsive:'-2: unresponsive',
            cancelling:'-64:cancelling', exited:'-1:exited', 
            retrying_connect:'65:retrying', connect_failed:'-64:connect_failed',
            downloading_results:'-3:downloading_results'}
            
states_user_sees = {null:'', ready:'ready', syncing:'syncing...', 
            uploading:'uploading...', synced:'synced', repairing:'repairing...',
            rendering:'rendering...', finished_render:'done!',
            finished_composite:'finished composite', sync_failed:'sync failed',
            render_cancelled:'-16: render cancelled', 
            frame_finished: '17: frame_finished',
            connecting:'connecting...', connected:'connected:', 
            no_network:'no network', unresponsive:'unresponsive',
            cancelling:'cancelling', exited:'exited', connect_failed:'failed to connect',
            retrying_connect:'retrying...', downloading_results:"Get tile..."
            }
            
report_levels = {"APOCOLYPSE":0, "SHES DEAD JIM":1,"PRETTY BAD":2,"ERROR":3, "WARNING":4, "INFO":6}

def get_parent_executable():
    """ return a path to the executable that is running the python interpreter
    
    Description:
        Python has two locations where it stores information about the currently running 
        executable, sys.executable, and also sys.argv. Usually sys.executable is reliable
        however in certain circumstances it can be wrong as it will in some
        contexts query the PATH env var to find the python exe that is running. If an 
        application changes this var during run time then sys.executable is wrong.
        
         """
         
         
    exe_path = ''
         
    if sys.argv:
        
    
    #is sys.argv[0] a valid path?
        if all( [os.path.exists(sys.argv[0]), os.path.isabs(sys.argv[0])] ):
        
            #we have a valid path, so we should override sys.executable
            
            exe_path = sys.argv[0]
            
        elif os.path.exists(sys.argv[0]):
            
            #we have a relative path, so we should check it matches with the sys.executable
            
            if os.path.basename(sys.executable) == os.path.basename(sys.argv[0]):
                
                #the path checks out so we use sys.executable
                exe_path = sys.executable
        
    else:
        
        #sys.argv is empty or the file path doesn't exist, fall back to sys.executable and pray to the
        # digital gods to be merciful
        
        exe_path = sys.executable
        
    return exe_path
        
        
                       
def setup_logging(name, level=logging.INFO, create_stream_hndlr=False, 
    #introduce the logging facility
    
    
    
    # if the log exists already, get it, don't create another one.
    base_app = "Not Set"):
    
    
           #  ' %(name)s ' + l_sep +\ # uncomment if you want to show the log's name
        
        # create file handler which logs even debug messages
        
    
    logger = CRLogging.setup_logging(name, level, create_stream_hndlr, base_app,
        cr_version =get_crowdrender_version())
    # Log that we're starting and the system parameters (aids with debugging)
    logger.info("######################  LOGGING START  #######################")
    logger.info("Blender Version ; " + str(bpy.app.version))
    logger.info("Bl Build type ; " + str(bpy.app.build_type))
    logger.info("Bl Build Branch ; " + str(bpy.app.build_branch))
    logger.info("Bl Platform ; " + str(bpy.app.build_platform))
    logger.info("Bl bundled python ver ; " + sys.version)
    logger.info("cr build type ; " + cr_build_type)
    logger.info("cr build branch ; " + cr_build_branch)
    logger.info("cr logging mode is ; " + str(level))
    logger.info("cr version is ; " + str(cr_version))
    logger.info("System architecture ; " + str(platform.machine()))
    logger.info("Computer name ; " + str(platform.node()))
    logger.info("Platform details ; " + str(platform.platform()))


    if platform.system() == 'Darwin':
        logger.info("OS version ; " + str(platform.mac_ver()))
    elif platform.system() == 'Linux':
        logger.info("OS distribution and version ; " +\
                     str(distro.linux_distribution(full_distribution_name=True)))
    elif platform.system() == 'Windows':
        logger.info("OS version ; " + str(platform.win32_ver()))
    
    return logger
        
def get_base_app_version():
    
    return "_".join(map(str, bpy.app.version))
    
    
def extract_level(message):
    """ returns a syslog like level based on message contents
    
    This method assumes that there is a descriptive tag in the message contents
    that tells what level the message is, such as:
    
    Info, Warning, error etc
    
    """ 
    
    level = 6 #senseable default, it the string has no description, assume its
                # just information only.
    
    assert type(message) is str
    #convert the message to entirely upper case letters, makes searching easier.
    search_string = message.upper()
    #search for each level in the text
    for lvl_name, lvl_number in report_levels.items():
        
        if lvl_name in search_string: level = lvl_number
        
        
    return level

def write_report_data_file(path, report_data=[], logger = None):
    """ write report data to a file
    """
    
    assert type(report_data) is list
    
    try:
    
    
        f = open(path, "at")

        for report in report_data:

            time_logged = int(time.time())

            json_obj = {"time_logged":time_logged,
                        "time_stamp":time.asctime(
                        time.localtime(time_logged)),
                        "message":report.rstrip("\n"),
                        "level":extract_level(report)}
                
            data_to_write = json.dumps(json_obj)


            f.write(data_to_write + "\n")

        f.close()
    
    except: 
    
        location = "utils.write_report_data_file"
        log_string =" could not open or write to report data file"
    
        handle_generic_except(location=location, log_string = log_string,
            logger = logger)
    

def timed_out(start_time, timeout):
    """ Basic timeout function, return true if the timeout is reached.
    
    INPUTS
    start_time - the time as given by time.perf_counter() when the timer is started
    timeout - the time out in seconds as a floating point number
    
    RETURNS
    boolean which is true when the timeout is expired and false at all other times.
    
       """

    if time.perf_counter() - start_time > timeout: return True
    else: return False
    
    
    

def get_machine_uuid():
    """ Queries the hardware UUID, falls back to NIC mac address on failure
    
    
        """
    
    import platform, re, subprocess, os, hashlib, uuid
    
    # Get the highest strength encryption guaranteed on this platform.
    # Note that sha512 is always present, the others might not be but we should use them
    # over sha algorithm
    hash_func_names = ['sha3_512', 'sha3_384', 'sha3_256', 'sha512']
           
    hash_funcs = [hashlib.new(name) for name in hash_func_names\
                 if name in hashlib.algorithms_guaranteed]
    
    hash_func = hash_funcs[0]
    
    os_type = platform.system()
    
    if os_type == 'Darwin':
    
        machine_uuid_str = ''
        
        p = os.popen('ioreg -rd1 -c IOPlatformExpertDevice | grep -E \'(UUID)\'', "r")
        
        while 1:
            line = p.readline()
            if not line: break
            machine_uuid_str += line
            
        match_obj = re.compile('[A-Z,0-9]{8,8}-' +\
                           '[A-Z,0-9]{4,4}-' +\
                           '[A-Z,0-9]{4,4}-' +\
                           '[A-Z,0-9]{4,4}-' +\
                           '[A-Z,0-9]{12,12}')
                           
        match = match_obj.findall(machine_uuid_str)[0]
        
        #see if we got an actual uuid or not
        try:
            verified = uuid.UUID(match)
        #if we can't find the uuid, fall back to using the mac address
        except ValueError: 
        
        
            match = str(uuid.uuid5(uuid.UUID(int=0), str(uuid.getnode())))
        
        
            
        hash_func.update(bytes(match, 'utf-8'))
        
        result = str(uuid.uuid5(uuid.UUID(int=0), hash_func.hexdigest()))
        
            
    elif os_type == 'Windows':
    
        import winreg
        
        cryptography = "SOFTWARE\Microsoft\Cryptography"
        hardwareconfig = "SYSTEM\HardwareConfig"
        
        key_crypto = None
        key_hardware = None
        mach_guid = ""
        hardw_uuid = ""
        
        
        
        try:
            #open keys
            key_crypto = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cryptography)
           
        
            #get values
        
            mach_guid  = winreg.QueryValueEx(key_crypto, "MachineGuid")[0]
            
        
        except: 
            
           pass
            
        try:
            
            key_hardware = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, hardwareconfig)
            hardw_uuid = winreg.QueryValueEx(key_hardware, "LastConfig")[0]
            
        except:
        
            pass
        
        # if both attempts to get a hardware id fail, then fallback to using the 
        # the mac address.
        
        if mach_guid == "" and hardw_uuid == "":
            
            mach_guid = str(uuid.getnode())
                        
        hash_func.update(bytes(mach_guid, 'utf-8'))
        hash_func.update(bytes(hardw_uuid, 'utf-8'))
        
        result = str(uuid.uuid5(uuid.UUID(int=0), hash_func.hexdigest()))
        
    elif os_type == "Linux":
        # TODO, linux needs upgrading to discover the actual hardware uuid,
        # the current method 
        # uses the network interface mac address, which is more likely to change
        # esp with the use of VPN adapters. Its not known to the team if the 
        # vpn had a mac addr on linux and if it could override the physcial 
        # interfaces.
        
        import uuid 
        
        machine_id_paths = ['/etc/machine-id', '/var/lib/dbus/machine-id']
        
        valid_machine_id_paths = [path for path in machine_id_paths\
                                         if os.path.exists(path)]
                                         
        if valid_machine_id_paths:
        
            f = open(valid_machine_id_paths[0], "rt")
            
            raw_id = f.readline().rstrip()
            
            machine_id = bytes(raw_id, 'utf-8')
            
            hash_func.update(machine_id)
            
            result = str(uuid.uuid5(uuid.UUID(int=0), hash_func.hexdigest()))
            
        else:
        
            try:
            
                hash_func.update(bytes(str(uuid.getnode()), 'utf-8'))
            
                result = str(uuid.uuid5(uuid.UUID(int=0), hash_func.hexdigest()))
            
            except:
        
                result = str(uuid.uuid1())
        
    return result
        
        
def get_machine_cores(logger):
    """ Returns number of CPU cores    """
    
    import multiprocessing
    
    cores = multiprocessing.cpu_count()
    
    logger.debug("UTILS:get_machine_cores" + l_sep + " number of CPU cores detected is" +\
        " " + str(cores))
    
    return cores
    
    
def get_computer_name():
    
    import platform
    
    return platform.node()     
    
def get_computer_os():
        
    import platform
    
    return platform.platform()   
    
def get_crowdrender_version():

    return "_".join(map(str, crowdrender.cr_version))                       
        

def set_screen_coords( coords = ()):
        
        import bpy
        
        scene = bpy.context.scene
        
        
            
        scene.render.border_min_x = coords[0]
        scene.render.border_max_x = coords[1]
        scene.render.border_min_y = coords[2]
        scene.render.border_max_y = coords[3]




def set_cr_path():
    import os
    
    user_preferences = bpy.context.preferences
    addon_prefs = user_preferences.addons[crowdrender.package_name].preferences
    project_path = addon_prefs.project_files
    
    if process == 'client' or \
       process == 'client_interface':
        
        cr_path = os.path.normpath(project_path + '/client')
        
    elif process == 'server_session' or \
         process == 'server_interface':
         
        cr_path = os.path.normpath(project_path + '/server')

    if not os.path.exists(cr_path):
        mkdir_p(cr_path)

#Create the cr_path string and then use this to create our cr directory


def mkdir_p(path):
    """Make a directory from 'path' if one doesn't exist"""
    
    try:
        os.makedirs(path, exist_ok=True)  # Python>3.2
    except TypeError:
        try:
            os.makedirs(path)
        except OSError as exc: # Python >2.5
            if exc.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else: raise
            
if not process == 'render_proc':     
    set_cr_path()


        
        
        
def get_cr_path():
    import os
    
    user_preferences = bpy.context.preferences
    addon_prefs = user_preferences.addons[crowdrender.package_name].preferences
    project_path = addon_prefs.project_files
                
    if process == 'client' or process == 'client_interface':
        cr_path = os.path.normpath(project_path + '/client')
        
    elif process == 'server_session' or process == 'server_interface':
        cr_path = os.path.normpath(project_path + '/server')
    
    return cr_path
    # the path may not exist, we create it if not.
    
def profile_func(func):
    """ profiles a function and all its sub calls using python's profile module
    """ 

    
    def inner(*args, **kwargs):
        
        print("CROWDRENDER FUNCTION PROFILER:")
        print("")
        print("PROFILING: ", func.__module__, ".", func.__name__)
        print("")
        
        profile = cProfile.Profile()
        
        profile.runcall(func, *args, **kwargs)
        
        profile.print_stats()
        
    return inner 

def func_time(func):
    """ returns a timed version of the function func.
        
        Methodology:
        
        Using the timing module, this function returns the function "inner"
        which wraps the argument function so that an approximate execution
        time will be output whenever the function is called. 
            
        
        arguments: func (function) the function you wish to time. 
        return value: function, the wrapped version of func
        side effects: None
        exceptions raised: None
        restrictions: Unknown
        """
    
    # define the wrapper function. This takes arbitrary arguments so it 
    # can cope with a variety of functions without needing knowledge of the
    # specifics of their arguments.
    
    def inner(*args, **kwargs):
        
        
        time_start = time.perf_counter()
        
        ret = func(*args, **kwargs)
        
        time_end = time.perf_counter()
        
        # optional statements to output the names of the arguments passed to
        # the func argument. This can be useful where you wish to know what
        # arguments were used in a particular call. 
        
        if hasattr(args[0], 'name'):
            str_out = args[0].name
        elif hasattr(args[1], 'name'):
            str_out = args[1].name
            
        elif hasattr(args[0], 'bl_rna'):
            str_out = args[0].bl_rna
        elif hasattr(args[1], 'bl_rna'):
            str_out = args[1].bl_rna
        else:
            str_out = "???"
        
        # to avoid many messages being output, we are only interested in 
        # calls that last more than a millisecond. 
        if (time_end-time_start > .001):
            print("TIMING :: ", func ,"acting on ::", str_out,
                  " :: ", time_end-time_start)
                  
        #End of if
        return ret
    #End of inner
    return inner
#End of func_time    

class UploadTask:
    """ an upload task represents the nodes, and their progress in uploading files """
    recipients = {}
    is_finished = False
    
    def __init__(self, files=[], storage_path=None):
        """
        Arguments:
            callback     = pyfunction(upload_task_id)
            storage_path = 'path where temp directory is created'
            """
            
        self.upload_task_id = uuid.uuid4().hex
        self.temp_folder = tempfile.TemporaryDirectory(dir = storage_path)
        self.recipients = {}
        self.files = []
        
    def add_files(self, files):
        
        for f in files:
            #append files as posix paths, even if they're on windows, win
            # still recognises a path with the '/' instead of '\' and it 
            # allows us to use os.path on unix like OSes without having
            # to have custom code.
            self.files.append(pathlib.Path(f).as_posix())
    
    def add_recipient(self, recipient, file):
        """ adds receivers of the file to the upload task
        Arguments:
            recipients = {'unique id':[list of paths]}
        
        Description:
            Each receiver is listed as recieving a set of files, as each reciever reports
            that it has all the files, its taken off the list of remaining receivers.
            
            The paths should be located in the temp_folder if the caller wants the 
            files to be cleaned up when the upload is complete.
        """
        
        
        rec = self.recipients.get(recipient, None)
        
        if rec is None:
            
            self.recipients[recipient] = []
            
        self.recipients[recipient].append(file)
        
    def timed_out(self):
        
        self.temp_folder.close()
    
    def update_task(self, recipient_uuid, file):
        """ updates the recipient with recipient_uuid
        
        Arguments: 
            recipient_uuid = (str) 'unique id'
            file           = (str) 'path of file being uploaded'
               
        """
    
        recipient = self.recipients.get(recipient_uuid, None)
        
        if recipient is not None: 
        
            recipient.remove(file)
            
            if len(recipient) == 0:
                #node finished
                self.recipients.pop(recipient_uuid)
             
        if len(self.recipients) == 0:
            # task is finished
            self.is_finished=True
            self.temp_folder.cleanup()
            

class CRWebRequest(threading.Thread):
    """ Thread based class to handle making HTTP requests
    
    This class uses the requests module to make HTTP requests in a 
    thread separate to the main branch of execution allowing non-
    blocking requests. 
    """
    #TODO: Change name to CRHTTPRequest
    
    def __init__(self, logger, zmq_contxt, comm_endpoint, request, timeout=0.0):
    
        
        threading.Thread.__init__(self, daemon=True)
        
        self.logger = logger
        self.timeout = timeout
        try:
            self.sock = zmq_contxt.socket(zmq.DEALER)
            self.sock.connect('inproc://' + comm_endpoint)
            self.request = request
            self.uuid = request[_uuid]
            
        
            self.start()
        
        except zmq.ZMQError as e:
            
            self.logger.error("CRWebRequest.__init__" + l_sep +\
                              "ZMQError detected whilst setting up sockets" +\
                              ". Error was" + str(e.strerror))
            
        except:
            
            import sys, traceback
                
            err_data = sys.exc_info()  
            tb_lines = traceback.extract_tb(err_data[2])
            
            self.logger.error("CRWebRequest.__init__" + l_sep +\
                     "request" + str(request) +\
                      " caused an exception." + str(err_data[0]) +\
                      ": " + str(err_data[1]))
            
            for frame in tb_lines:
                 
                self.logger.warning("CRWebRequest.__init__"  + l_sep +\
                     " " + frame.filename + " on line: " + str(frame.lineno) +\
                     " in: " + frame.name)
            
    def get_sanitised_request_payload(self, request_payload):
        
        for redacted_item in ('username', 'password'):
            
            if redacted_item in request_payload:
                
                return "CONTENT REDACTED"
        
        return request_payload 
    
    def get_sanitised_request_headers(self, request_headers):
        
        san_hdr_items = []
        
        for hdr, val in request_headers.items():
            
            if 'authorization' in hdr:
                val = "REDACTED"
                
            san_hdr_items.append(
                "   " + str(hdr) + " : " + str(val) + "\n")
            
        return "".join(san_hdr_items)
        
        
    def run(self):
    
        import requests
        
        rqst_payload = self.request[payload]
        rqst_url = self.request.get(config.url_api, self.request.get(config.url_auth))
        rqst_headers = self.request[headers]
        request_type = self.request[http_request_type]
        
        
        try:
            response = requests.request(
                request_type,
                rqst_url,
                data=rqst_payload,
                headers=rqst_headers,
                timeout = self.timeout
            )
            
            if response.status_code >= 200 and response.status_code < 300:
                
                try:
                    
                    resp_contents = response.json()
                    
                except ValueError:
                    
                    resp_contents = {server_error:str(response.content),
                                    _uuid:self.uuid}
                                    
                    log_string = [
                        "Unsuccessful https Request \n",
                        "Response Code : ", str(response.status_code), "\n",
                        "Request URL : ", rqst_url, "\n",
                        "Request type : ", request_type, "\n",
                        "Request headers : ", self.get_sanitised_request_headers(
                            rqst_headers), "\n",
                        "Request body : ", self.get_sanitised_request_payload(
                            rqst_payload), "\n",
                        "Response body : ", str(response.content)
                    ]
                    
                    self.logger.warning("".join(log_string))
                        
                except zmq.zmqError as e:
                    
                    resp_contents = {zmq_error:"zmqError " + str(e),
                                        _uuid:self.uuid}
                    self.zmq_error = e
                    
                finally:
                    
                    resp_msg = MsgWrapper(message = request_response,
                        attributes = {request_response:resp_contents,
                                        _uuid:self.uuid})
                                        
                    e = getattr(self, 'zmq_error', None)
                    
                    if e is not None:
                                        
                        if e.errno == zmq.ETERM:
                    
                            self.logger.info("CRWebRequest.run:" + l_sep +\
                                "Attempted to process response" + str(response) +\
                                " but context had terminated, exiting")
                    
                        else:
                
                            self.sock.send_string(json.dumps(resp_msg.serialize()))
                    
                    else:
                        
                        self.sock.send_string(json.dumps(resp_msg.serialize()))
                
            else:
                
                try:
                    
                    
                    log_string = [
                        "Unsuccessful https Request \n",
                        "Response Code : ", str(response.status_code), "\n",
                        "Request URL : ", rqst_url, "\n",
                        "Request type : ", request_type, "\n",
                        "Request headers : ", self.get_sanitised_request_headers(
                            rqst_headers), "\n",
                        "Request body : ", self.get_sanitised_request_payload(
                            rqst_payload), "\n",
                        "Response body : ", str(response.content)
                    ]
                    
                    self.logger.warning("".join(log_string))
                    
                    resp_contents = response.json()
                    
                    resp_msg = MsgWrapper(
                        message = request_response,
                        attributes = {
                            request_response:resp_contents,
                            _uuid:self.uuid
                        }
                    )
                    
                    self.sock.send_string(json.dumps(resp_msg.serialize()))
                
                except ValueError:
                    
                    resp_contents = {server_error:str(response.content),
                                    _uuid:self.uuid}
                    
                    resp_msg = MsgWrapper(
                        message = request_response,
                        attributes = {
                            request_response:resp_contents,
                            _uuid:self.uuid
                        }
                    )
                    
                    self.sock.send_string(json.dumps(resp_msg.serialize()))
                    
                    log_string = [
                        "Response contents not a json object \n",
                        "Response Code : ", str(response.status_code), "\n",
                        "Request URL : ", rqst_url, "\n",
                        "Request type : ", request_type, "\n",
                        "Request Headers : ", self.get_sanitised_request_headers(
                            rqst_headers), "\n",
                        "Request body : ", self.get_sanitised_request_payload(
                            rqst_payload), "\n",
                        "Response body : ", str(response.content)
                    ]
                    
                    self.logger.warning("".join(log_string))
            
                                    
        except requests.exceptions.Timeout:
        
            resp_msg = MsgWrapper(message = request_response,
                attributes = {_uuid:self.uuid,
                    request_response:req_timed_out})
                
            self.sock.send_string(json.dumps(resp_msg.serialize()))
            
        except requests.ConnectionError as e:
            
            resp_msg = MsgWrapper(message = request_response,
                attributes = {_uuid:self.uuid,
                    request_response:connect_error})
                
            self.sock.send_string(json.dumps(resp_msg.serialize()))
            
            
        except zmq.ZMQError as e:
            
            if e.errno == zmq.ETERM:
                #Exit, don't reply with the result of the request the client is gone
                self.logger.info("CRWebRequest.run:" + l_sep +\
                    "received a HTTP response but the server is shutting down" +\
                    " going to discard the response and close.")
            
        except:
            
            handle_generic_except(
                "CRWebRequest.run:",
                "Unexpected error when trying to request from discovery :",
                self.logger)
                  
            resp_msg = MsgWrapper(message = request_response,
                attributes = {_uuid:self.uuid,
                    request_response:{"error":str(err_data[1])}})
                
            self.sock.send_string(json.dumps(resp_msg.serialize()))
            
            
        
        #self.sock.disconnect('inproc://login_threads')
        self.sock.close()    
    

class MsgWrapper:
    """ Wrapper class for sending/receivin msgs using a json serialisation format
    
    The MsgWrapper is a helper class that contains arbitrary data contained in an
    internal py dictionary called 'attributes'. There are also four members for 
    convenient storage/access of command or message flags, task uuids and session uuids.
    
    Arguments:
    attributes:         dict   - container for key:value storage of data
    command, message:   string - flags 
    t_uuid:             bytes - Unique id for tasks, used as identity for msg routing
    s_uuid:             bytes - Unique id for sessions, used as id for msg routing
    
    Returns:
        python dictionary   -   {string - attribute_name: attribute_value}
    
    Exceptions Raised:
        ValueError  -   If the s_uuid, t_uuid or public_key arguments are not bytes objects
                        then a ValueError will be raised indicating the error and giving the
                        type of the argument that was incorrect.
                        
    Side Effects:
        None
        
    Description:
    
    Note on uuids, CR uses session and task uuids for routing of msgs. These uuids should
    never be modified as this will likely corrupt the data flow and result in msgs no
    longer being recv'd/sent.
    
    NOTE: s_uuid and t_uuid are converted to a string using utf-8 conversion prior to 
    being serialized for sending. This is because the json lib in python cannot serialize
    a bytes object
    
    """
    
    #used for pattern matching when receiving a msg from zmq
    keys = ['attributes', 'command', 'message',
            's_uuid', 't_uuid', 'public_key']
    
    def __init__(self, attributes={}, command='', message='', t_uuid = b'', s_uuid = b'',
        public_key = b''):
        """ Constructor for the MsgWrapper class
        """
        
        
                 
        
        self.attributes = attributes
        self.command = command
        self.message = message
        
        #important to raise here as the expected format for sending is a bytes object
        # as defined in the doc string for this class.
        if type(s_uuid) is bytes: self.s_uuid = s_uuid
        else: 
            raise ValueError("Expected a bytes object, but got a " +\
                 str(type(s_uuid)) + " instead.")
        if type(t_uuid) is bytes: self.t_uuid = t_uuid
        else: 
            raise ValueError("Expected a bytes object, but got a " +\
                 str(type(t_uuid)) + " instead.")
        if type(public_key) is bytes: self.public_key = public_key
        else: 
            raise ValueError("Expected a bytes object, but got a " +\
                 str(type(public_key)) + " instead.")
        
        
    def serialize(self):
        """ Flatten a MsgWrapper object to a format suitable for serialisation
        
        Arguments: None
        
        Returns: {
                            
                    "attributes": self.attributes,
                    "command": self.command,
                    "message": self.message,
                    "t_uuid": ser_t_uuid,
                    "s_uuid": ser_s_uuid,
                    "public_key": ser_p_key
                            
                    }
        """
    
        return          {
                            
                            "attributes": self.attributes,
                            "command": self.command,
                            "message": self.message,
                            "t_uuid": self.t_uuid.decode('utf-8'),
                            "s_uuid": self.s_uuid.decode('utf-8'),
                            "public_key": self.public_key.decode('utf-8')
                            
                        }

    def create_msg(data):
        
        s_update = MsgWrapper()
        
        s_update.attributes     = data["attributes"]
        s_update.command        = data["command"]
        s_update.message        = data["message"] 
        s_update.t_uuid         = bytes(data["t_uuid"], 'utf-8')
        s_update.s_uuid         = bytes(data["s_uuid"], 'utf-8')
        s_update.public_key     = bytes(data["public_key"], 'utf-8')
        
        return s_update
        

    @classmethod
    def deserialize(cls, data):
        """ Create MsgWrapper object from json string version of the same
        
        Arguments: 
        data : dict() that's been created from the json string version of 
        the serialized MsgWrapper object
        
        returns: MsgWrapper object initialised with contents of data
        
        """
        s_update = None
        # if the data is frames of a message, we look at each one
        if isinstance(data, dict):
            #process as a dict
            if all(key in MsgWrapper.keys for key in data.keys()):
                s_update = cls.create_msg(data)
            else:
                raise TypeError("MsgWrapper.deserialize; msg did not match cr MsgWrapper signature")
            
        #if the data is a string, we could have json formatted object as a string
        elif isinstance(data, str):
            #check we have a valid signature before attempting to loads
            if all(key in data for key in MsgWrapper.keys):
                
                json_ob = json.loads(data,object_hook=as_BTObject)
                
                s_update = cls.create_msg(json_ob)
                
            else:
                raise TypeError("MsgWrapper.deserialize; msg did not match cr MsgWrapper signature")
            
                
        elif isinstance(data, bytes):
            
            if all(bytes(key, 'utf-8') in data for key in MsgWrapper.keys):
            
                json_str = data.decode('utf-8')
                
                json_ob = json.loads(json_str,object_hook=as_BTObject)
            
                s_update = cls.create_msg(json_ob)
                
            else:
                raise TypeError("MsgWrapper.deserialize; msg did not match cr MsgWrapper signature")
            
                
        elif isinstance(data, list):
            
            for msg_parts in data:
                
                if isinstance(msg_parts, dict):
            #process as a dict
                    if all(key in MsgWrapper.keys for key in msg_parts.keys()):
                        s_update = cls.create_msg(msg_parts)
                        break
                    else:
                        continue
            
                    
                #if the data is a string, we could have json formatted object as a string
                elif isinstance(msg_parts, str):
                    #check we have a valid signature before attempting to loads
                    if all(key in msg_parts for key in MsgWrapper.keys):
                        
                        json_ob = json.loads(data,object_hook=as_BTObject)
                        
                        s_update = cls.create_msg(json_ob)
                        break
                    else:
                        continue
            
                        
                elif isinstance(msg_parts, bytes):
                    
                    if all(bytes(key, 'utf-8') in msg_parts for key in MsgWrapper.keys):
                        
                        json_str = msg_parts.decode('utf-8')
                
                        json_ob = json.loads(json_str,object_hook=as_BTObject)
                    
                        s_update = cls.create_msg(json_ob)
                        break
                    else:
                        continue
        
        if s_update is None: raise TypeError("""MsgWrapper.deserialize; 
            attempted to deserialize a msg: """ + str(data)+ """ which resulted in 
            no valid msg object being generated""")
        

        return s_update        
    
        
class BTEncoder(json.JSONEncoder):
    
    def default(self, obj):
        
        if isinstance(obj, Vector):
            
            if len(obj) == 3:
                return {'__vector__':'Vector', 'x':obj.x, 'y':obj.y, 'z':obj.z}
            elif len(obj) == 2:
                return {'__vector__':'Vector', 'x':obj.x, 'y':obj.y}
            else:
                raise
            
        elif isinstance(obj, Euler):
            return {'__euler__':'Euler', 'order':obj.order, 
                         'x':obj.x, 'y':obj.y, 'z':obj.z}
        elif isinstance(obj, Color):
            return {'__color__':'Color', 'r':obj.r, 'b':obj.b, 'g':obj.g} #,
                        #'h':obj.h, 's':obj.s, 'v':obj.v} #removed as was causing the 'b'
                        # value to change on de serialising
        
        elif isinstance(obj, complex):
            
            return {'__complex__':'complex', 'imag':obj.imag, 'real':obj.real}
        
        elif isinstance(obj, (bpy.types.bpy_prop_array,)):
            
            items = list()
            
            for item in obj:
            
                #if the item is a builtin type we just append it to the list
                
                if isinstance(item, (int, float, bool, str)):
                
                    items.append(item)
                    
                # where we have the complex type, its not json serializable, 
                # so we have to pack it ourselves.
                
                elif isinstance(item, (complex,)):
                
                    complx = {'__complex__':'complex','real':item.real, 
                                'imag':item.imag}
                    
                    items.append(complx)
                
            return {'__proparray__':items}
            
        elif isinstance(obj, set):
            
            #return a list instead of a set
            return {'__set__':[ x for x in obj ]}
            
        elif isinstance(obj, Quaternion):
            return {'Quaternion':'Quaternion', 
                         'x':obj.x, 'y':obj.y, 'z':obj.z, 'w':obj.w}
            
            
        else:
            try:
                return json.dumps(obj)
            except:
                print('could not serialise ', obj)
                return json.JSONEncoder.default(self, None)
    
def as_BTObject(dct):

    if '__vector__' in dct:
        # we use 4 since the length of the dct includes the entry for 
        # the type of object the dct represents.
        if len(dct) == 4:
            
            return Vector(( dct['x'], dct['y'], dct['z']))
        
        elif len(dct) == 3:
            
            return Vector(( dct['x'], dct['y']))
        
    elif '__euler__' in dct:
        euler_obj = Euler(( dct['x'], dct['y'], dct['z']))
        euler_obj.order = dct['order']
        
        return euler_obj
        
    elif 'Quaternion' in dct:
        quaternion_obj = Quaternion(( dct['x'], dct['y'], dct['z'], dct['w']))
        
        return quaternion_obj
        
    elif '__color__' in dct:
        color_obj = Color()
        color_obj.r = dct['r']
        color_obj.g = dct['g']
        color_obj.b = dct['b']
        # color_obj.h = dct['h']
#         color_obj.s = dct['s']
#         color_obj.v = dct['v']
        return color_obj
    
    elif '__complex__' in dct:
        
        return complex(dct['real'], dct['imag'])
        
    elif '__proparray__' in dct:
    
        #note we're returning a list not a prop array
        # however, its been tested ok to assign a list 
        # to a prop_array in blender. 
    
        prop_list = list()
        
        values = dct['__proparray__']
    
        for item in values:
            
            if isinstance(item, (dict,)):
                
                if '__complex__' in item:
                    
                    prop_list.append(complex(item['real'], item['imag']))
            else:
                
                prop_list.append(item)
                
        return prop_list
                
            
    elif '__set__' in dct:
        # return a set of the resulting dictionary
        return set(dct['__set__']) 
        
    else:
        return dct

    
def handle_generic_except(location, log_string, logger=None):
    """ handle a general exception, log data to logger
    
    Arguments:
        location:       string  -   "class_name.method"
        log_string:     string  -   text to print to log file
        logger:         logging.logger  -   logger to use
    Returns: 
        nothong
    Side Effects:
        logs error data to a log file
    Exceptions:
        None
        
    Description:
        Handles general exceptions which are not expected to 
        occurr in the try block. The logging statment given in 
        the arguments is appended by the traceback data so that 
        the complete picture of what happened is captured in the
        logs.
        If there is no logger object given as an argument the error
        msg will be printed to stdout
    """
                
    import sys, traceback

    err_data = sys.exc_info()  
    tb_lines = traceback.extract_tb(err_data[2])    
    
    log_str = log_string + " " + str(err_data[0]) +\
              ": " + str(err_data[1])
    
    if logger is not None:
    
        
    
        err_strings = [frame.filename + " on line: " + str(frame.lineno) +\
                 " in: " + frame.name + "\n" for frame in tb_lines]
        err_str = "".join(err_strings)
        
        logger.error(log_str + "\n" +err_str)
        
    else:
        print(log_str + "\n")
        
        for frame in tb_lines:
            print(frame.filename, " on line:", frame.lineno, " in: ", frame.name)
            
        
