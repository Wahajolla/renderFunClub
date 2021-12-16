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
""" Module for read/write and mgmt of config data.
"""

### IMPORT

import os, json, sys

top_level_pckg = __package__.split(".")[0]

crowdrender_mod = sys.modules.get(top_level_pckg)

cr_token = 'cr_token'
cr_version = 'cr_version'
network_timeout = 'network_timeout'
node_perf_data = 'node_perf_data'
documentation = 'documentation'
port_range = 'port_range'
show_analytics_notification = 'show_analytics_notification'
show_req_notification ='show_req_notification'
start_port = 'start_port'
upload_analytics_data = 'upload_analytics_data'
url_api = 'url_api'
url_api_reporting = 'url_api_reporting'
url_auth = 'url_auth'


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
    
    err_strings = [frame.filename + " on line: " + str(frame.lineno) +\
             " in: " + frame.name + "\n" for frame in tb_lines]
             
    err_str = "".join(err_strings)
    
    if logger is not None:
    
        
        
        logger.error(log_str + "\n" +err_str)
        
    else:
    
        print(log_string + "\n" + err_str)


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
            
            
config_defaults = {
            cr_version:crowdrender_mod.bl_info['version'],
            start_port:9669,
            port_range:10,
            cr_token:'',
            network_timeout:30.0,
            node_perf_data:{},
            url_api:"https://discovery.crowd-render.com/api/v02/graph",
            url_api_reporting:"https://discovery.crowd-render.com/api/v02/reporting",
            url_auth:"https://discovery.crowd-render.com/login",
            show_req_notification:True,
            show_analytics_notification:True,
            upload_analytics_data:True,
            documentation:"https://www.crowd-render.com/documentation-v030"
            }

def is_version_higher(base_version, comparison_version):
    """ Returns True if comparison_version is a higher revision than base_version
    
    Arguments:
        base_version        -  list    [    int -   major revision number,  
                                            int -   minor revision number,
                                            int -   patch revision number
                                        ]
        comparison_version  -   list (see base_version, its the same thing)
        
    Returns:
        boolean             - True if the comparison version is higher than the 
                            base_version
    Side Effects:
        None
    Exceptions:
        TypeError:          - if arguments are not lists, TypeError will be raised, they 
                                should be lists [major, minor, patch]
        ValueError:         - if argumnets are not the right shape, value error is raised   
                                should be a list of three ints (see TypeError and 
                                Arguments section above)
    Description:
        Simple comparion of two versions of crowdrender addon. The comparison simply turns
        the version number into an integer, using each revision number as a power of ten.
        So:
            comparison number = major * 100 + minor * 10 + patch 
        This gives a unique integer for any revision number that will always be lower
        than a later revision.
        
    """ 
    if not type(base_version) in (list, tuple) or\
         not type(comparison_version) in (list, tuple):
        raise TypeError("Arguments must be of type list [major, minor, patch]")
        
    elif len(base_version) != 3 or len(comparison_version) != 3:
        raise ValueError("Arguments must be lists with three integers - [major, minor"+\
            ", patch]")
    
    base_v_comp_num = 100 * base_version[0] + 10 * base_version[1] + base_version[2]
    comparison_v_com_num = 100 * comparison_version[0] + 10 * comparison_version[1] +\
         comparison_version[2]
    
    if comparison_v_com_num > base_v_comp_num: res = True
    else: res = False
    
    return res

def read_config_file(keys = []):
    """ Return a python dictionary of whole configuration or requested config items
    
    Description:
    
    This function returns a list of configuration data. If no argument is provided then
    the function will return the entire contents of the configuration file as a 
    python dictionary object  {key:value}.
    Config items are stored as name:value
    
    Arguments:
    
    key = [] - python list, a list of keys for which the values are required from the 
        configuration file
    
    Return value:
    {key:value} - a dictionary containing the key:value pairs for each key requested
    
    Side Effects:
        Will generate default config file if there is no config file
        Will use defaults if the key cannot be found in the file
    
    """
    
    # locate the configuration file - if the file can't be found, create one using 
    # global defaults
    
    config_dirpath = os.path.normpath(os.path.expanduser("~/cr/.conf"))
    
    # we need to be sure this path actually exists cause if not then it must be 
    # created before we can do anything else.
    if not os.path.exists(config_dirpath):
        mkdir_p(config_dirpath)
        
    config_filepath = os.path.join(config_dirpath, "config")
    
    # generate the defaults from hard coded
    if not os.path.exists(config_filepath):
        f = open(config_filepath, "wt")
        srl_conf_defaults = json.dumps(config_defaults, indent=0)
        f.write(srl_conf_defaults)
        
        # make sure that if the user specifies an empty list, they get all config items
        if keys == []: keys = config_defaults.keys()
        
        results = {key:config_defaults[key] for key in keys}
    
    else:
        
        # get the config items from the config file
        f = open(config_filepath, "rt")
        
        srl_conf = ''
        
        for line in f.readlines():
            srl_conf += line
        
        try:
            config_items = json.loads(srl_conf)
            
            conf_file_cr_version = config_items.get(cr_version)
            
        except:
            # if we can't load the config items, fall back to defaults and log the 
            # error to the console
            location = 'utils.read_config_file'
            log_string = 'exception whilst trying to get: '+ str(keys)
            
            handle_generic_except(location, log_string)
            
            conf_file_cr_version = None
            config_items = {}
            
        
        # take care of versioning within the conf file since its not updated on a new
        # install and we need to change things like the discovery API version we post to
        if conf_file_cr_version is None or is_version_higher(
            conf_file_cr_version, config_defaults[cr_version]):
            # overwrite upgradable parts of the conf file
            
            new_items = {cr_version:config_defaults[cr_version],
                        url_api:config_defaults[url_api],
                        url_auth:config_defaults[url_auth],
                        url_api_reporting:config_defaults[url_api_reporting]}
                        
            
            config_items.update(new_items)
            
            sorted_items = {key:config_items[key] for key in sorted(config_items)}
            
            
            write_config_file(conf_items = sorted_items)
        # make sure that if the user specifies an empty list, they get all config items
        if keys == []: keys = config_items.keys()
        
        results = {}
        
        #Get the requested items, using the config defaults as a fallback if 
        # the key results in no item being recovered from the file.
        for key in keys:
        
            results[key] = config_items.get(key, None)
            
            if results[key] is None:
            
                results[key] = config_defaults[key]
        
        
    f.close()
        
    return results

def write_config_file(conf_items ={}):
    """ Write items to the config file
    
    Description:
    
    This function allows items to be written to the configuration file as a 
    python dictionary object {key:value}.
    Config items are stored as name:value
    
    Arguments:
    
    conf_items = {key:value} - python dict, a single python dict containing all the items in 
        key:value format.
    
    Return value:
    Integer - 0 means the write failed, 1 means sucecssful
    
    Side Effects:
    Will generate defaults alongside user defined config items if there is no config file  
    
    Errors Raised:
    Will raise an exception if either the input argument is empty or not a dictionary
    
    """
    import shutil
    
    # Its an error to not write anything to the config rile using this function
    # or to enter something other than a dictionary
    if conf_items =={}: raise
    elif not type(conf_items) is dict: raise
    
    config_dirpath = os.path.normpath(os.path.expanduser("~/cr/.conf"))
    
    # we need to be sure this path actually exists cause if not then it must be 
    # created before we can do anything else.
    if not os.path.exists(config_dirpath):
        mkdir_p(config_dirpath)
        
    config_filepath = os.path.join(config_dirpath, "config")
    
    # generate the defaults from hard coded
    if not os.path.exists(config_filepath):
    
        f = open(config_filepath, "wt")
        
        #get the default items and the new and make sure that the new take precedence
        # (this is what the update method is used for)
        items_to_write = config_defaults
        new_items = {key:value for key, value in conf_items.items()}
        
        sorted_items = {key:new_items[key] for key in sorted(new_items)}
        
        items_to_write.update(sorted_items)
        
        # write items to the file
        srl_conf_defaults = json.dumps(items_to_write, indent=0)
        f.write(srl_conf_defaults)
        f.close()
        
        results = 1
    
    else:
        
        
         # get the config items from the config file
        f = open(config_filepath, "rt")
        
        srl_conf = ''
        
        for line in f.readlines():
            srl_conf += line
            
        f.close()
        
        try:
            config_items = json.loads(srl_conf)
            
        except json.decoder.JSONDecodeError:
        
            config_items = {}
            
            location = 'utils.write_config_file'
            log_string = 'Json decoder error, could not read the config file.'
            
            handle_generic_except(location, log_string)
            
            
        
        except:
        
            config_items = {}
            
            location = 'utils.write_config_file'
            log_string = 'unexpected exception whilst trying to read: ' +\
                str(config_items)
            
            handle_generic_except(location, log_string) 
        
        new_items = {key:value for key, value in conf_items.items()}
        config_items.update(new_items)
        
        sorted_items = {key:config_items[key] for key in sorted(config_items)}
        
        # write items to the file
        srl_conf_defaults = json.dumps(sorted_items, indent=0)
        f = open(config_filepath + "_temp", "wt")
        f.write(srl_conf_defaults)
        f.close()
        
        #swap temp file for real file, safer in case we're interrupted
        shutil.copy2(config_filepath + "_temp", config_filepath)
        
        
        results = 1
        
    
        
    return results