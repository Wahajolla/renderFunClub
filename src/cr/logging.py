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

"""logging - provide logger objects for use in logging system info

Purpose

    Provides logging capability for logging to file, stdout and to discovery's server

Input/Output

    N/A 

How

    Uses built in logging module from python and extends functionality in areas 
    like setting up a configured logger in a convenience function which only requires
    the caller to supply a name. 
    
    Also configures a handler to log to discovery remotely so we can get errors and
    warnings from every session running crowdrender. 
    
 

Modules Imported

    logging
    
Classes Exported
    
    CRHTTPSHandler
    

Exceptions Raised

    None

Functions Exported

    setup_logging(log_name, level=logging.INFO, create_stream_hndlr = False):


"""

### IMPORT 
import logging, os, json, requests
from . import config
from . config import mkdir_p, read_config_file

l_sep = ';' #separator character for logging messages/records
_loggers = {}

logging.raiseExceptions = False #should be false unless you want to check for 
                    #errors in the logging code.

def get_logging_path():
    
    logging_path = os.path.expanduser("~") + os.path.normpath("/cr/logging")
    
    return logging_path

def setup_logging(log_name, level=logging.INFO, create_stream_hndlr = False, 
            base_app = "Not set", cr_version = "not set", raise_except=False
            ):
    """ Return a logging object for use with logging in the CR system
    
    Arguments:
    
    Returns:
    
    Side Effects:
    
    Exceptions:
    
    Description:
    
    
    """ 
    
    
    #introduce the logging facility
    import platform
    
     
    
    # if the log exists already, get it, don't create another one.
    if _loggers.get(log_name):
        logger = _loggers.get(log_name)
    else:    
        logger = logging.getLogger(log_name)
        
        _loggers[log_name] = logger
    
        ## CREATE FORMATTERS
    
        if level == logging.DEBUG:
            
            formatter = logging.Formatter(
            '%(asctime)s ' + l_sep +\
            ' %(name)s ' + l_sep +\
            ' %(levelname)s ' + l_sep +\
            ' %(message)s'
            )
        else:
         
           
            formatter = logging.Formatter(
            '%(asctime)s ' + l_sep +\
           #  ' %(name)s ' + l_sep +\ # uncomment if you want to show the log's name
            ' %(levelname)s ' + l_sep +\
            ' %(message)s'
            )
        
        logger.setLevel(level)  #can set this lower e.g DEBUG as required
        # create file handler which logs even debug messages
        #Create handlers
        https_h = CRHTTPSHandler(base_app, cr_version) # create a https handler to log to discovery
        fh = MakeFileHandler(os.path.join(get_logging_path(),
            log_name + '.log'))
        
        https_h.setLevel(logging.WARNING) # we only want warning and above
        fh.setLevel(level)

        https_h.setFormatter(formatter)
        fh.setFormatter(formatter)
        
        # add the handlers to the logger
        logger.addHandler(https_h)
        logger.addHandler(fh)
    
    
        #if there is a console, then the following code would be useful
        if create_stream_hndlr:
    
            ch = logging.StreamHandler()
            ch.setLevel(level)
            ch.setFormatter(formatter)
            logger.addHandler(ch)         

    return logger
    
class MakeFileHandler(logging.FileHandler):
    def __init__(self, filename, mode='a', encoding=None, delay=0):            
        mkdir_p(os.path.dirname(filename))
        logging.FileHandler.__init__(self, filename, mode, encoding, delay)
        
def logging_shutdown():
    """ Shutdown the logging system
    """
    logging.shutdown()
    
class CRHTTPSHandler(logging.Handler):
    """
    A class which sends the log message to discovery.
    
    """
    
    def __init__(self, base_app, cr_version):
        """
        Initialise everything, and i mean everything!
        
        """
        logging.Handler.__init__(self)
        self.base_app = base_app
        self.cr_version = cr_version
    

    def emit(self, record):
        """ Sends a record to Discovery's reporting server in JSON format.
        
        Arguments:
            record: - logging.LogRecord - part of the logging package in python
            
        Returns:
            None
            
        Side Effects:
            Sends a msg in JSON format to the logging endpoint on discovery for
            collecting diagnostic data.
            Will also read the value of upload_analytics_data from the config file
            to determine whether to send data to discovery or not. If the user
            decides to turn this off, we detect this more or less immediately and 
            log nothing to the server.
            
        Exceptions:
            None
        
        Description
        """
        import platform
        
        #here we extract the message part and send it to the server
        data = {'location':record.module + ":" + record.funcName + " Line # " +\
                    str(record.lineno),
                'errorLevel':record.levelname,
                'message':record.msg,
                'env':{ 
                    'os': platform.system() + ":" + \
                        str(platform.architecture()),
                    'baseAppVersion': self.base_app,
                    'crVersion': self.cr_version
                    }
                }
        
        try:
            
            config_data = read_config_file(
                [config.cr_token, 
                config.url_api_reporting,
                config.upload_analytics_data])
            
            upload_analytics = config_data[config.upload_analytics_data]
            
            if upload_analytics:
                                            
                token = config_data[config.cr_token]
                url = config_data[config.url_api_reporting]
            
                headers = {'cache-control': 'no-cache',
                             'Authorization': 'Bearer ' + token, 
                             'content-type': 'application/json', 
                             'Accept': 'application/json'}
                         
                body = json.dumps(record.__dict__)
            
                response = requests.request("POST", url, 
                                        data=json.dumps(data), 
                                        headers=headers, timeout = 30 )
            
        except Exception:
        
            self.handleError(record)