# This file is proprietary to Crowd Render Pty Limited and is confidential.

# <sort of PEP8 Compliant, lines are not always 79 chars long>
# $LastChangedDate: 2021-05-17 08:39:39 +1000 (Mon, 17 May 2021) $
# $LastChangedBy: jamesharrycrowther $

"""
crowdrender blender python package for crowd accelerated rendering

This package implements a multi-process, multi-machine distributed
rendering addon for Blender.

This package exports the following modules:

 
attributes - definitions for blender data blocks and their attributes
cl_int_start - script for managing starting a CIP process
client_interface - separate process for managing render nodes
config - managment for config files
crender_engine - defines a class based on Blender's API class RenderEngine 
hash_tree - define a custom hash tree for data checking between nodes
network_engine - manage network traffic between nodes
rules - defines how blender's data is searched and hashed
serv_int_start - script to start a SIP process
server_interface - server process, manages incoming requests to a render node
server_session - background process of blender, accepts data updates, render commands
serv_int_start - script to start a server session process
settings - define settings for each scene
ui_operators - define Blender operators
ui_panels - define Blender panels
utils - utility functions and classes

"""

### IMPORTS
import  sys

try:
    import bpy
except:
    print("skipped bpy, assume you're unit testing then?")

import rna_keymap_ui

from . logging import setup_logging, l_sep
from . config import read_config_file, write_config_file


# Following the convention in
# http://wiki.blender.org/index.php/Dev:2.5/Py/Scripts/Cookbook/Code_snippets/
# Multi-File_packages
# This block of code is used whenever blender is started to import the modules
# (.py files) of the crowdrender package.

### PACKAGE GLOBALS


# override package name so that the choice of render engine
# for users does not include the silent crowdrender engine, this engine merely
# allows us to gather render results and inject them into blender, its not an actual
# render engine, more a pipeline manager.
top_level_pkg = __package__.split(".")[0]
crowdrender_mod = sys.modules.get(top_level_pkg)
cr_build_type = 'release'
cr_build_branch = 'tagged/cr_031_bl280+ r$LastChangedRevision: 1767 $'
cr_version = crowdrender_mod.bl_info['version']
package_name = top_level_pkg


#Here we create a logger to capture any issues we might have with enabling the addon
# we have recurrent problems with imports failing on windows with DLLs not being
# found, this might be due to virus detection.

import imp, subprocess, sys, os

import bpy
from bpy.app.handlers import persistent
from bpy.types import AddonPreferences
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty

process = 'client'

# IMPORTS

try:
    
    logger = setup_logging("CR_Main", base_app = "_".join(map(str, bpy.app.version)))
    
    import zmq
    
    
except:

    location = "__init__"
    log_string = "Error detected whilst attempting to import packages"
    #had an error whilst attempting to import stuff
    
    import sys, traceback

    err_data = sys.exc_info()  
    tb_lines = traceback.extract_tb(err_data[2]) 
    
    error_msg = [" " + frame.filename + " on line: " + str(frame.lineno) +\
                 " in: " + frame.name + "\n" for frame in tb_lines]
    
    err_str = "".join(error_msg)
    
    logger.error(location + l_sep + log_string + l_sep +\
        err_str)
        
    raise ImportError("CrowdRender is not able to run because it can't import necessary"+\
        "components, please e-mail us at info@crowdrender.com.au to report this.")
        
     


def update_start_port(self, context):
    #self["lower_port_range"] = value
    print(value)

def update_port_range(self, context):
    #self["upper_port_range"] = value
    print(value)

def update_timeout_prefs(self, context):

    from . config import write_config_file, network_timeout

    write_config_file({network_timeout:float(self["network_timeout"])})
    
def update_analytics_pref(self, context):
    
    from . config import write_config_file, upload_analytics_data
    
    
    
    write_config_file({upload_analytics_data:bool(self[upload_analytics_data])})
    
    
    


class CRAddonPreferences(AddonPreferences):
    # this must match the addon name, use '__package__'
    # when defining this in a submodule of a python package.
    bl_idname = package_name


    store_path = os.path.normpath(os.path.expanduser("~/cr"))
    
    use_debug: BoolProperty(
        name="Use pydev debugging",
        description='Requires remote_debugger addon enabled',
        options = {'HIDDEN'},
        default=False
    )

    project_files: StringProperty(
        name = '',
        description = 'Choose a Directory',
        default = store_path,
        maxlen = 1024,
        subtype = 'DIR_PATH')

    network_timeout: StringProperty(
        name = "network timeout",
        description = "timeout used for connecting or declaring a node unresponsive",
        default = "30.0",
        update = update_timeout_prefs)

    start_port: IntProperty(
        name = " Starting port to use on the network",
        description = " Used as the starting value for the range of ports that crowdrender uses, " +\
            "a restart is required if this is changed.",
        update = update_start_port,
        default = 9669
        )

    port_range: IntProperty(
        name = " Port Range",
        description = " Used for setting the range of ports that crowdrender uses, " +\
            "a restart is required if this is changed.",
        update = update_port_range,
        default = 10,
        min = 2
        )
        
    upload_analytics_data: BoolProperty(
        name = "upload analytics data",
        description = "Allow the addon to send warnings, errors and performance data",
        update = update_analytics_pref,
        default = config.read_config_file(
            [config.upload_analytics_data])[config.upload_analytics_data]
        )
     
         
    
    def draw(self, context):

        layout = self.layout
        
        logging_path = os.path.normpath(os.path.expanduser("~/cr/logging"))
                     
        prj_files_box = layout.box()
        prj_files_box.label(text='Files')
        prj_files_box.label(text='Set the directory where '+\
            'CrowdRender will store output files')
        prj_files_box.prop(self,'project_files')

        layout.separator()
        
        logs_box = layout.box()
        logs_box.label(text = "Logs")
        logs_box.label(text = 'Log file packaging' + " (Log files located in: " +\
                 logging_path + ")")
        row = logs_box.row()
        row.separator()
        row.operator("crowdrender.log_file_package")


        row.label(text = "  : Space used for logs :  " +\
          str(
            sum(os.path.getsize(os.path.join(logging_path, f) ) \
            for f in os.listdir(logging_path) \
            if os.path.isfile(os.path.join(logging_path, f))
               ) / 1000000
              ) + " MB"
                )
        
        layout.separator()
        issues_box = layout.box()
        issues_box.label(text='Bug Reporting')
        row = issues_box.row()
        row.separator()
        row.operator("crowdrender.report_issue")
        row.label(text = " Opens a web browser to our bug tracker web form")



        layout.separator()
        
        network_box = layout.box()
        network_box.label(text = "Network")
        network_box.label(text = 'Value in seconds used for timeouts when communicating with'+\
                ' other nodes in the network', icon = 'SETTINGS')

        network_box.prop(self, 'network_timeout')
        
        network_box.separator()
        
        network_box.label(text = 'Port range to use for crowdrender, note, if you have a'+\
                ' firewall enabled on your nodes, you will want to allow TCP traffic '+\
                'on ports in the range you specify below in order for nodes to be '+\
                'able to connect.',
                icon = 'SETTINGS')

        network_box.prop(self, 'start_port')
        network_box.prop(self, 'port_range')
        
        layout.separator() 
        
        debugging_box = layout.box()        
        
        debugging_box.label(text='Debugging')
        debugging_box.label(text='Enable debugging using pydev ' +\
            '(requires remote debugging addon enabled and a debug server running)',
                     icon = 'ERROR')
        debugging_box.separator()
        debugging_box.prop(self, 'use_debug')
        
        layout.separator()
        
        analytics_box = layout.box()
        analytics_box.label(text = 'Analytics')
        row = analytics_box.row(align = True)
        row.prop(self, "upload_analytics_data")


def user_session():

    global CRInitialiser

    class CRInitialiser:
        """ The CRInitialiser runs when blender is loaded. It configures the Addon in
        blender including the user interface options and compatible rendering engines.
        It also creates an interface to access other machines on the network.
        """



        def cr_import(self):
            """Imports/reloads py files from the CR package into blenders memory.
            """

            #These variables have to be global so that each time this method is run
            #it accesses the same reference. If we don't do it the program
            # gives an error on reload because it's
            #attemping to access an undefined variable.

            global crender_engine
            global hash_tree
            global network_engine
            global settings
            global ui_operators
            global ui_panels
            # global update_handler

            if "ready_to_reload" in globals():
                import imp
                imp.reload(settings)
                imp.reload(ui_operators)
                imp.reload(ui_panels)
                imp.reload(crender_engine)
                imp.reload(hash_tree)
                imp.reload(network_engine)


                # imp.reload(update_handler)
                print("\n CROWD RENDER addon reloaded successfully \n ")

            #   Otherwise, if we have started blender and the addon is enabled by
            # default, or if we have started blender then activated the addon via the
            # user-prefs, import all the modules for the first time.

            else:

                from . import settings
                from . import ui_operators
                from . import ui_panels
                from . import crender_engine
                from . import hash_tree
                from . import network_engine


                # from crowdrender import update_handler

            # When reloading we need to use different functions, this switch is set
            # so that the first time the module is imported, the else statement
            # above is executed ensuring a proper import. For subsequent reloads
            # we need to use the imp.reload function instead.

            global ready_to_reload
            ready_to_reload = True

        #End of import()





        def register_package(self):
            """Perform the registration of the crowd render python package

            This function is responsible for calling all other sub module register
            functions and then calling blender's module register method. It is
            part of a larger system which ensures that crowd render is not
            registered during start-up. Rather reg is delayed until bpy.data has
            the 'objects' collection as an attribute. This ensures that we can safely
            import other code from add-ons we support, such as cycles.

            """

            # It is vital that we remove the event_register function from the
            # list of handlers as soon as the module is registered, if not we will
            # continually trigger the registration code over and over since the
            # event_register will continually be called and call this function.
            ### Risk No.7 It is possible that some day, this event might not fire
            # each time the screen is redrawn. We take advantage of this fact and
            # at some point we may wish to look at using the load event instead,
            # though at this stage the prototype code seems to work ok.

            #bpy.app.handlers.load_post.remove(scene_update_fwd)

            self.cr_import()

            settings.register()

            ui_operators.register()

            ui_panels.register()

            crender_engine.register()



            print("Crowd Render user_session add-on enabled")

        #End of register_package()

        def unregister(self):


            crender_engine.unregister()
            ui_panels.unregister()
            ui_operators.unregister()
            settings.unregister()
            ui_panels.unregister()


            print("Crowd Render add-on Disabled")

         #End of unregister()

    #-------------------------End of class------------------------------------


def client_int_proc():

    global CRInitialiser
    global process
    process = 'client_interface'

    class CRInitialiser:
        """ The CRInitialiser runs when blender is loaded. It configures the
        Addon in blender including the user interface options and compatible
        rendering engines. It also creates an interface to access other
        machines on the network.
        """

        # def __init__(self):

            # self.register()



        #End of __init__()

        # def register(self):



        # #End of register()

        def cr_import(self):
            """Imports/reloads  py files from the CR package into blenders memory.
            """
            
            #These variables have to be global so that each time
            # this method is run it accesses the
            #same reference. If we don't do it the
            #program gives an error on reload because it's
            #attemping to access an undefined variable.
            
            
            global client_interface
            
            if "ready_to_reload" in globals():
                import imp
                
                imp.reload(client_interface)
                print("\n CROWD RENDER addon reloaded successfully \n ")
                
            #   Otherwise, if we have started blender and the addon is enabled by
            # default, or if we have started blender then activated the addon via the
            # user-prefs, import all the modules for the first time.

            else:


                from . import client_interface

            # When reloading we need to use different functions, this switch is set
            # so that the first time the module is imported, the else statement
            # above is executed ensuring a proper import. For subsequent reloads
            # we need to use the imp.reload function instead.

            global ready_to_reload
            ready_to_reload = True

        #End of import()



        def register_package(self):
            """Perform the registration of the crowd render python package

            This function is responsible for calling all other sub module register
            functions and then calling blender's module register method. It is
            part of a larger system which ensures that crowd render is not
            registered during start-up. Rather reg is delayed until bpy.data has
            the 'objects' collection as an attribute. This ensures that we can safely
            import other code from add-ons we support, such as cycles.

            """

            # It is vital that we remove the event_register function from the
            # list of handlers as soon as the module is registered, if not we will
            # continually trigger the registration code over and over since the
            # event_register will continually be called and call this function.
            ### Risk No.7 It is possible that some day, this event might not fire
            # each time the screen is redrawn. We take advantage of this fact and
            # at some point we may wish to look at using the load event instead,
            # though at this stage the prototype code seems to work ok.

            #bpy.app.handlers.scene_update_post.remove(scene_update_fwd)

            self.cr_import()

            # settings.register()

            # ui_operators.register()


            # bpy.utils.register_module(__name__)

            # self.process_start()




            print("Crowd Render Client Interface Process ready")

        #End of register_package()

        def unregister(self):


            # ui_operators.unregister()
            # settings.unregister()


            print("Crowd Render add-on Disabled")

#-------------------------End of class--------------------------------------

def server_int_proc():

    global CRInitialiser
    global process
    process = 'server_interface'

    class CRInitialiser:
        """ The CRInitialiser runs when blender is loaded. It configures the
        Addon in blender including the user interface options and compatible
        rendering engines. It also creates an interface to access other
        machines on the network.
        """

        # def __init__(self):

            # self.register()



        #End of __init__()

        # def register(self):



        # #End of register()

        def cr_import(self):
            """Imports/reloads py files from the CR package into blenders memory.
            """

            #These variables have to be global so that each
            # time this method is run it accesses the
            #same reference. If we don't do it the program
            # gives an error on reload because it's
            #attemping to access an undefined variable.

            global server_interface

            if "ready_to_reload" in globals():
                import imp

                imp.reload(server_interface)

                print("\n CROWD RENDER addon reloaded successfully \n ")

            #   Otherwise, if we have started blender and the addon is enabled by
            # default, or if we have started blender then activated the addon via the
            # user-prefs, import all the modules for the first time.

            else:


                from . import server_interface

            # When reloading we need to use different functions, this switch is set
            # so that the first time the module is imported, the else statement
            # above is executed ensuring a proper import. For subsequent reloads
            # we need to use the imp.reload function instead.

            global ready_to_reload
            ready_to_reload = True

        #End of import()



        def register_package(self):
            """Perform the registration of the crowd render python package

            This function is responsible for calling all other sub module register
            functions and then calling blender's module register method. It is
            part of a larger system which ensures that crowd render is not
            registered during start-up. Rather reg is delayed until bpy.data has
            the 'objects' collection as an attribute. This ensures that we can safely
            import other code from add-ons we support, such as cycles.

            """

            # It is vital that we remove the event_register function from the
            # list of handlers as soon as the module is registered, if not we will
            # continually trigger the registration code over and over since the
            # event_register will continually be called and call this function.
            ### Risk No.7 It is possible that some day, this event might not fire
            # each time the screen is redrawn. We take advantage of this fact and
            # at some point we may wish to look at using the load event instead,
            # though at this stage the prototype code seems to work ok.

            #bpy.app.handlers.scene_update_post.remove(scene_update_fwd)

            self.cr_import()

            # settings.register()

            # ui_operators.register()



            # bpy.utils.register_module(__name__)

            # self.process_start()




            print("Crowd Render Server Interface Process ready")

        #End of register_package()

        def unregister(self):


            # ui_operators.unregister()
            # settings.unregister()
            # bpy.utils.unregister_module(__name__)

            print("Crowd Render add-on Disabled")

def server_session_proc():

    global CRInitialiser
    global process
    process = 'server_session'

    class CRInitialiser:
        """ The CRInitialiser runs when blender is loaded. It configures the
        Addon in blender including the user interface options and compatible
        rendering engines. It also creates an interface to access other
        machines on the network.
        """

        # def __init__(self):

            # self.register()



        #End of __init__()

        # def register(self):



        # #End of register()

        def cr_import(self):
            """Imports/reloads py files from the CR package into blenders memory.
            """

            #These variables have to be global so that each
            # time this method is run it accesses the
            #same reference. If we don't do it the program
            # gives an error on reload because it's
            #attemping to access an undefined variable.


            global server_session

            if "ready_to_reload" in globals():
                import imp

                imp.reload(server_session)
                imp.reload(crender_engine)
                print("\n CROWD RENDER addon reloaded successfully \n ")

            #   Otherwise, if we have started blender and the addon is enabled by
            # default, or if we have started blender then activated the addon via the
            # user-prefs, import all the modules for the first time.

            else:


                from . import server_session
                from . import crender_engine
            # When reloading we need to use different functions, this switch is set
            # so that the first time the module is imported, the else statement
            # above is executed ensuring a proper import. For subsequent reloads
            # we need to use the imp.reload function instead.

            global ready_to_reload
            ready_to_reload = True

        #End of import()



        def register_package(self):
            """Perform the registration of the crowd render python package

            This function is responsible for calling all other sub module register
            functions and then calling blender's module register method. It is
            part of a larger system which ensures that crowd render is not
            registered during start-up. Rather reg is delayed until bpy.data has
            the 'objects' collection as an attribute. This ensures that we can safely
            import other code from add-ons we support, such as cycles.

            """

            # It is vital that we remove the event_register function from the
            # list of handlers as soon as the module is registered, if not we will
            # continually trigger the registration code over and over since the
            # event_register will continually be called and call this function.
            ### Risk No.7 It is possible that some day, this event might not fire
            # each time the screen is redrawn. We take advantage of this fact and
            # at some point we may wish to look at using the load event instead,
            # though at this stage the prototype code seems to work ok.

            #bpy.app.handlers.scene_update_post.remove(scene_update_fwd)

            self.cr_import()

            # settings.register()

            # ui_operators.register()



            # bpy.utils.register_module(__name__)

            # self.process_start()




            print("Crowd Render Server Session Process ready")

        #End of register_package()

        def unregister(self):


            # ui_operators.unregister()
            # settings.unregister()
            # bpy.utils.unregister_module(__name__)

            print("Crowd Render add-on Disabled")


#-------------------------End of class--------------------------------------

def render_proc():

    global CRInitialiser
    global process
    process = 'render_proc'

    class CRInitialiser:
        """ The CRInitialiser runs when blender is loaded. It configures the
        Addon in blender including the user interface options and compatible
        rendering engines. It also creates an interface to access other
        machines on the network.
        """

        def cr_import(self):
            """Imports/reloads py files from the CR package into blenders memory.
            """
            
            #These variables have to be global so that each
            # time this method is run it accesses the
            #same reference. If we don't do it the program
            # gives an error on reload because it's
            #attemping to access an undefined variable.
            global crender_engine
            
            
            if "ready_to_reload" in globals():
                import imp
                imp.reload(crender_engine)
                
            #   Otherwise, if we have started blender and the addon is enabled by
            # default, or if we have started blender then activated the addon via the
            # user-prefs, import all the modules for the first time.
            
            else:
                
                from . import crender_engine
                
            # When reloading we need to use different functions, this switch is set
            # so that the first time the module is imported, the else statement
            # above is executed ensuring a proper import. For subsequent reloads
            # we need to use the imp.reload function instead.
            
            global ready_to_reload
            ready_to_reload = True
            
        #End of import()



        def register_package(self):
            """Perform the registration of the crowd render python package

            This function is responsible for calling all other sub module register
            functions and then calling blender's module register method. It is
            part of a larger system which ensures that crowd render is not
            registered during start-up. Rather reg is delayed until bpy.data has
            the 'objects' collection as an attribute. This ensures that we can safely
            import other code from add-ons we support, such as cycles.

            """
            
            # It is vital that we remove the event_register function from the
            # list of handlers as soon as the module is registered, if not we will
            # continually trigger the registration code over and over since the
            # event_register will continually be called and call this function.
            ### Risk No.7 It is possible that some day, this event might not fire
            # each time the screen is redrawn. We take advantage of this fact and
            # at some point we may wish to look at using the load event instead,
            # though at this stage the prototype code seems to work ok.
            
            print("REGISTERING CRENGINE")
            
            self.cr_import()
            
            crender_engine.register()
            
        
        #End of register_package()
        
        def unregister(self):
            
            crender_engine.unregister()
            # ui_operators.unregister()
            # settings.unregister()
            # bpy.utils.unregister_module(__name__)
            
            pass #print("Crowd Render add-on Disabled")


#-------------------------End of class--------------------------------------


#-------------------------INITIALISATION SWITCHES---------------------------





#------------------------REGISTRATION OF HANDLERS---------------------------

@persistent
def scene_update_fwd(scene):
    initialiser.event_register(scene)


addon_keymaps = []
def register():
    """ Start the register process for crowd render

    Unlike a lot of other packages, we do not register our package
    straight away, instead we subscribe to the scene_update event and
    use our event_register function to trigger the registration at the
    right time.

    """
    
    
    # here we go!!# sometimes blender will try to register this class more than once
    # on enable, to avoid this breaking stuff we wrap in try/except and
    # catch the error to continue if its already registered. Would be
    # nice if the error was specific to the class already existing.
    # This error can also occur if the class is not a subclass of
    # of a registrable type.
    try:
        bpy.utils.register_class(CRAddonPreferences)
        global zmq_context
        zmq_context = zmq.Context()
    except:
        
        
        
        print("error encountered" +\
                          " whilst attempting to register addon prefs")
        err_data = sys.exc_info()
        
        print("error was ... " +\
              str(err_data[0]) +" : " +str(err_data[1]) )
        
        
    # We switch the definition of our class based on what role a particular
    # instantiation has.
    
    init_funcs = {'client_int_proc':client_int_proc,
                  'server_int_proc':server_int_proc,
                  'server_session_proc':server_session_proc,
                  'render_proc':render_proc}
    
    initialise = None
    
    for args in sys.argv:
        if args in init_funcs:
            initialise = init_funcs[args]
            break

    # If this is not a user session, run the retrieved init function. Valid
    # use cases for this are initialising a client interface process,
    # server interface process or server session process.

    if initialise is not None:
        initialise()
    elif not bpy.app.background:
        user_session()
    else:
        render_proc()


    global initialiser
    initialiser = CRInitialiser()

    initialiser.register_package()

    #add keymap entries
    kcfg = bpy.context.window_manager.keyconfigs.addon
    if kcfg:
        km = kcfg.keymaps.new(name = 'Screen', space_type = 'EMPTY')
        
        kmi = km.keymap_items.new('crowdrender.render_still', 'F12', 'PRESS', \
            ctrl=False, shift=False, alt=True)    
        kmi.properties['cr_animation'] = False         
        
        kma = km.keymap_items.new('crowdrender.render_anim', 'F12', 'PRESS', \
            ctrl=False, shift=True, alt=True)
        kma.properties['cr_animation'] = True

        addon_keymaps.append((km, kmi))
        addon_keymaps.append((km, kma))
#End of register()

def unregister():
    # global initialiser #NOTE: you only need to declare a name global if you
    # are going to assign to that name inside a local scope, such as a
    # function, method or class. If you are just reading that name
    # you can simply use it without global.
    try:

        bpy.utils.unregister_class(CRAddonPreferences)
        global zmq_context
        zmq_context.destroy(linger=0)

    except:



        self.logger.error("error encountered" +\
                          " whilst attempting to register addon prefs")
        err_data = sys.exc_info()

        self.logger.error("error was ... " +\
              str(err_data[0]) + str(err_data[1]) )


    initialiser.unregister()
    
    #unregister kmi's
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
        
    addon_keymaps.clear()
    

#End of unregister()


if __name__ == '__main__':
    register()
