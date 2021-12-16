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
settings - define settings for each scene

Purpose

The user will desire to set various settings for each scene. An example of
such settings is choice of render engine and all the associated settings, 
render layers, passes to include and so on. 

Input/Output

Input is from Blender's window management system which fills in the
data for each property defined in this module

Output is simply the population of the settings with the data extracted
from the UI system.


How

This module subclasses the Property types of blender. This allows us to 
store our settings within blender and associate them with a particular 
scene or session (.blend file).

Information on generating custom properties for storing settings of a 
blender addon can be found here:

http://wiki.blender.org/index.php/Doc:2.6/Manual/Extensions/Python/Properties

Modules Imported

Classes Exported

Exceptions Raised

Functions Exported


"""

import bpy, imp, threading, sys
from . import utils, network_engine

from bpy.props import (BoolProperty,
                       EnumProperty,
                       FloatProperty,
                       IntProperty,
                       PointerProperty,
                       StringProperty)

crowdrender = sys.modules[__package__]
                       
# This should eventually be placed inside a function that can be called
# to interrogate the addons package and see what engines there are. We
# could even take this one step further and see if we can automate the 
# process of hooking into engines for support. Or maybe, if we get lucky
# define our own API and let the addon community use our platform. This
# would make a lot more sense since what we are actually doing is more 
# of a platform solution than an engine. 

# note documentation on this enumeration is here:
# http://www.blender.org/documentation/blender_python_api_2_69_1/bpy.props.html


                       
# We need to refer to the module that an engine comes from in various
# parts of the CR package. This dictionary will make that task much
# easier as it can be easily accessed and will be dynamically updated
# to show the currently loaded render engines.
message_icons = {0:"ERROR", 1:"ERROR", 
                2:"ERROR", 3:"ERROR", 
                4:"ERROR", 5:"INFO", 
                6:"INFO"}

#monkey patching replacement for cycles' own poll method for the subdivision
#panel which won't appear when crowdrender is selected unless patched. 
@classmethod
def poll(cls, context):
    return (context.scene.render.engine in 'CYCLES') and\
         (context.scene.cycles.feature_set == 'EXPERIMENTAL') or\
         (context.scene.cycles.feature_set == 'EXPERIMENTAL') and\
         (context.scene.crowd_render.render_engine == 'CYCLES')

def get_engine_panels(engine):
    
    panels = []
    
    if engine == 'cycles':
        cycles = sys.modules[engine]
        panels = cycles.ui.get_panels()
        panels.extend([
            panel for panel in cycles.ui.classes\
                if hasattr(panel, 'COMPAT_ENGINES')])
        #replace the poll function with our own that allows the 
        # subdivision panel to show when crowdrender is the selected engine
        cycles.ui.CYCLES_RENDER_PT_subdivision.poll = poll
        
    elif engine == 'BLENDER_EEVEE':
        panels = [panel for panel in bpy.types.Panel.__subclasses__()\
                  if hasattr(panel, 'COMPAT_ENGINES') and \
                  'BLENDER_EEVEE' in panel.COMPAT_ENGINES]
        #stupid inconsistent panel definition in blender's 
        # properties_view_layer.py
        #need to make sure this version of blender has this panel too
        eevee_crypto_panel = getattr(
            bpy.types,
            'VIEWLAYER_PT_layer_passes_cryptomatte',
            None
        )
        if eevee_crypto_panel is not None:
            panels.append(bpy.types.VIEWLAYER_PT_layer_passes_cryptomatte)
        
    if not panels:
        raise RuntimeError("Could not get panels from " + engine.__name__)
        
    return panels

def change_render_engine_selection(self, context):
    """ handle an update to the render engine selection"""
    #and our new render engine is
    print("render engine changed to: ", self.render_engine)
    
    engine_modules = {
        eng_mod.bl_idname:eng_mod.__module__ \
            for eng_mod in bpy.types.RenderEngine.__subclasses__()
    }
    engine_modules.update({'BLENDER_EEVEE':'BLENDER_EEVEE'})
    #look for method to get panels 
    panels = get_engine_panels(engine_modules[self.render_engine])
    
    #remove 'crowdrender' from all panels
    for panel in bpy.types.Panel.__subclasses__():
        
        if hasattr(panel, 'COMPAT_ENGINES') and \
            'crowdrender' in panel.COMPAT_ENGINES:
            panel.COMPAT_ENGINES.remove('crowdrender')
            
    #add ourselves to all panels
    for panel in panels: panel.COMPAT_ENGINES.add('crowdrender')
            
    
def get_render_engines(self, context):
    #get addons list
    
    engines = [
        (
            eng.bl_idname,
            eng.bl_label,
            "".join(
                [
                eng.bl_label,
                " render engine"
                ] 
            ) 
        ) for eng in bpy.types.RenderEngine.__subclasses__()\
           if eng.bl_idname != crowdrender.package_name]
    
    engines.append(
        (
            "BLENDER_EEVEE",
            "Eevee",
            "Eevee render engine"
            )
        )
    
    
    return engines
    
def report_message_set(self, context):
    self.level = self.report_levels[self.message]
                       
def manual_loadb_update(self, context):
    """ Update handler for changes to the manual load balance value
    """
    context.scene.crowd_render.active_load_balance_node = self.name
    
   

class IpAddressProps(bpy.types.PropertyGroup):
    
    
    device_name: StringProperty(name = "", default="")
    device_address: StringProperty(name = "", default="")
    hardware_port_name: StringProperty(name = "", default="")
    
bpy.utils.register_class(IpAddressProps)

def name_update(self, context):
    
    client = sys.modules.get(__package__ + ".client", None)
    
    if not client is None:
    
        cr_client = getattr(client, 'cr_client', None)
        
        if not cr_client is None:
            cr_client = client.cr_client
    
            if self.node_uuid in cr_client.machines:
                cr_client.machines[self.node_uuid].cr_node = self.name

def comp_device_update(self, context):
    context.area.tag_redraw()
    
def threads_update(self, context):
    self.process_threads = self.node_machine_cores
    context.area.tag_redraw()
                
class ComputeDevices(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='name',
                                    default='')
    use: bpy.props.BoolProperty(name='use',
                                    default=True)
    id: bpy.props.StringProperty(name='id',
                                    default='')
    type: bpy.props.StringProperty(name ='type',
                                    default='CPU')
    
class UserRenderEngineChoice(bpy.types.PropertyGroup):
    
    name:  StringProperty(name="name", default='')
    engine: StringProperty(name="engine", default='')
    use_persistent: BoolProperty(name = "use persistent", default=False)
    
class CloudIssue(bpy.types.PropertyGroup):
    """ Container type for representing error messages from discovery
    """
    error_message: bpy.props.StringProperty(name = "error message",
                                            default = "")
    time_stamp: bpy.props.StringProperty(name = "time stamp",
                                        default = "")
                                        
    time_logged: bpy.props.IntProperty(name = "time logged",
                                        default = 0)
class NodeReport(bpy.types.PropertyGroup):
    """ Container type for representing error messages from discovery
    """
    name: bpy.props.StringProperty(name = "Message")
    message: bpy.props.StringProperty(name = "message",
                                            default = "")
    level: bpy.props.IntProperty(name = "message level")
    time_stamp: bpy.props.StringProperty(name = "time stamp",
                                        default = "")
    time_logged: bpy.props.IntProperty(name = "time logged",
                                        default = 0)

class NodeReportList(bpy.types.UIList):
    """  provides feedback to user as a list of messages/events
    """
    def draw_item(self, context, layout, data, item, 
                    icon, active_data, active_propname, index, flt_flag):
        """ Draw list of errors from discovery
        """
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            self.use_filter_sort_reverse = True
            issue = item
            layout.prop(issue, "message", 
                        text="", 
                        emboss=False, icon=message_icons[item.level])
    
class CloudIssuesList(bpy.types.UIList):
    """ An object representing an issue report from BG
    """ 
    
    
    def draw_item(self, context, layout, data, item, 
                    icon, active_data, active_propname, index, flt_flag):
        """ Draw list of errors from discovery
        """
        #show newest items first
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
        
            self.use_filter_sort_reverse = True
        
            issue = item
        
            layout.prop(issue, "error_message", 
                        text="", 
                        emboss=False, icon="ERROR")
    

    
bpy.utils.register_class(ComputeDevices)
bpy.utils.register_class(UserRenderEngineChoice)
bpy.utils.register_class(CloudIssue)
bpy.utils.register_class(CloudIssuesList)
bpy.utils.register_class(NodeReport)
bpy.utils.register_class(NodeReportList)

    
class CRNodes(bpy.types.PropertyGroup):

    name:  bpy.props.StringProperty(
        name = "Node", 
        default="new node", 
        update= name_update)
            
    node_address:  bpy.props.StringProperty(name = "ip address", default = "")
    node_state:  bpy.props.IntProperty(name = "machine state", default =0)
    node_uuid:  bpy.props.StringProperty(name = "machine uuid", default ="")
    node_access_key:  bpy.props.StringProperty(name = "session id", default ="")
    node_image_coords:  bpy.props.FloatVectorProperty(
        name = "screen coordinates",
        description = "tile offset and size",
        default = (0.0, 1.0, 0.0, 1.0),
        size = 4)
    
    node_machine_cores: bpy.props.IntProperty(name="machine_cores", default =0)
    
    cr_version: bpy.props.StringProperty(
        name = "cr version",
        description = "cr addon version",
        default = ""
        )
                                            
    node_local:  bpy.props.BoolProperty(
        name = "local",
        description = "node is on the local network",
        default = True)
                                            
    node_sync_progress:  bpy.props.IntProperty(
        name = "sync progress",
        description = "percent complete on sync",
        default = 1
                                            )
                                            
    node_render_progress:  bpy.props.IntProperty(
        name = "render progress",
        description = "percent complete on render",
        default = 1
        )
                                            
    node_result_progress:  bpy.props.IntProperty(
        name = "result transfer progress",
        description = "percent complete download",
        default = 0
        )
    
    node_repair_item: bpy.props.StringProperty(
        name = "Item under repair",
        description = "data which is currently " +\
        "not correct on the rendder node and an "+\
        "attempt is being made to " +\
        "repair it.",
        default = ""
        )
    
    
    node_active:  bpy.props.BoolProperty(
        name = "node active", 
        description = "Node is up",
        default= False)                                        
    
    node_render_active:  bpy.props.BoolProperty(
        name = "render active",
        description = "Node included in the render",
        default = True)
                                            
    node_tile_x:  bpy.props.IntProperty(
        name = "node tile x",
        description = "tile_x size in pixels",
        default = 0,
        min=0, max = 65536)
    
    node_tile_y:  bpy.props.IntProperty(
        name = "node tile y",
        description = "tile_y size in pixels",
        default = 0,
        min=0, max = 65536)
        
    process_threads: bpy.props.IntProperty(
        name = "process_threads",
        description = "Number of CPU threads to use simultaneously while rendering",
        default = 0,
        min=0, max=65536)                                        
                        
    node_A_manual:  bpy.props.FloatProperty(
        name = "node manual render tile size",
        description = "The fraction of the total area of the "+\
                    "image that will be given to this node to"+\
                    " render",
        default = 0.001,
        update = manual_loadb_update, 
        min = 0.001, max = 1.0
        )
    
    node_A_auto:  bpy.props.FloatProperty(
        name = "node render tile size",
        description = "The fraction of the total area of the "+\
                    "image that will be given to this node to"+\
                    " render",
        default = 0.001,
        min = 0.001, max = 1.0
        )
                                            
    compute_devices:  bpy.props.CollectionProperty(type = ComputeDevices)
    
    compute_device:  bpy.props.EnumProperty(name = 'compute_device',
        default = 'CPU',
        items = [
            ('CPU','CPU','Select CPU Rendering'),
            ('CUDA','CUDA','Select CUDA devices'),
            ('OPTIX','OPTIX', 'Select Optix devices'),
            ('OPENCL','OPENCL','Select OpenCL devices')],
        update = comp_device_update)
                                    
    reports:            bpy.props.CollectionProperty(type = NodeReport)
    
    report_index:       bpy.props.IntProperty(
        name = "active report", 
        description = "index of the active report",
        min = 0,
                                                ) 
                                                
    node_report_path:   bpy.props.StringProperty(
        name = "path to reports file for this node",
        default = "")  
    
    threads_mode: bpy.props.EnumProperty(
        name = 'threads_mode',
        default = 'Auto-detect',
        items = [
            ('Auto-detect','Auto-detect',
            'Automatically determine the number of threads based on CPU'),
            ('Fixed','Fixed','Manually determine the number of threads')],
        update = threads_update)
                                            
class CrowdRenderSceneSettings(bpy.types.PropertyGroup):
    """Define the container for crowdrender's settings
    
    """
    render_engine:  EnumProperty(
        items=get_render_engines,
        name="Render Engine",
        description="The render engine you wish to use with crowdrender",
        update=change_render_engine_selection
        )
        
        #LESSON: Had a bug here that lost me about an hour and half
        # default has to be a member of the items argument. If not
        # you will get an error telling you that default is not
        # in the enum members.
        
        
    use_cloud_rendering:  BoolProperty(
        name = "Open Cloud Rendering Panel",
        description= "",
        default = False
        )
        
    data_is_updated:  BoolProperty(
        name="data is updated",
        description = " refers to whether a mesh, curve"+\
        " or surface has been changed",
        default = False
        )
    
    status:  IntProperty(
        name = "status",
        description = "the current status of the system",
        default = 0,
        min = 0,
        max = 255
        )
        
        
        
    node_render_active:  BoolProperty(
        
        name = "render active",
        description = "Node rendering active",
        default = True)
            
    manual_load_balancer:  BoolProperty(
        name = "load balancer manual",
        description ="true if the load balancer is in manual mode",
        default = False)
            
            
    active_load_balance_node:  StringProperty(
        name="active load balance node",
        description="the node currently having its screen space value edited ",
        default = ""
        )
        
    local_node:  PointerProperty(
        name ="local",
        description = "local node i.e. this computer",
        type = CRNodes
        )
    
    @classmethod
    def register(cls):
        """Add the crowd render properties to the current scene
        
        """
        #debug if needed
        #print(dir(cls))
        bpy.types.Scene.crowd_render =  PointerProperty(
            name="Crowd Render Settings",
            description="Crowd Render settings",
            type=cls
            )
        
        
        
    @classmethod
    def unregister(cls):
        """Remove the crowd render properties from the current scene
        
        """
        if hasattr(bpy.types.Scene, 'crowd_render'):
            del bpy.types.Scene.crowd_render


#-------------------------End of class--------------------------------------


def num_cloud_instantes_update(self, context):
    """ Change the number of instances to request on discovery
    """
    bpy.ops.crowdrender.change_instance_number('INVOKE_DEFAULT')    
    
    print("updating the cloud instances requested")


class CrowdRenderGlobalSettings(bpy.types.PropertyGroup):
    """Define the container for crowdrender's settings
    
    """
    
   
        
    session_uuid: StringProperty(
        name = "Session UUID",
        description="Unique identifier for the active user session",
        maxlen = 128,
        default = ""
        )
    
    
    @classmethod
    def register(cls):
        """Add the crowd render properties to the current scene
        
        """
        #debug if needed
        #print(dir(cls))
        
        
        bpy.types.Text.cr = PointerProperty(
            name="Crowd Render Settings",
            description="Crowd Render settings",
            type=cls
            ) 
        
        
        
    @classmethod
    def unregister(cls):
        """Remove the crowd render properties from the current scene
        
        """
        if hasattr(bpy.types.Object, 'cr'):
            del bpy.types.Object.cr
            
class CrowdRenderTempProperties(bpy.types.PropertyGroup):
    """ Define a property group for storing temporary values
    """            

    render_engines_selected: bpy.props.CollectionProperty(
        type = UserRenderEngineChoice)
                                    
    cloud_system_issues: bpy.props.CollectionProperty(
        type = CloudIssue)  
                                    
    cr_issue_index:   bpy.props.IntProperty(
        name = "active issue", 
        description = "index of the active issue",
        min = 0,
                            )
     
    status: IntProperty(
        name = "status",
        description = "the current status of the system",
        default = 0,
        min = 0,
        max = 255
        )
        
    logged_in: BoolProperty(
        name ="Crowdrender server authenticated",
        options = {'SKIP_SAVE'},
        description = "boolean property, True if user is authenticated",
        default =False
        )
            
    password: StringProperty(
        name = "password",
        options = {'SKIP_SAVE'},
        subtype = 'PASSWORD',
        description = "password used to login to cloud services",
        default = ''
        )
            
    user_name: StringProperty(
        name = "user name",
        description = "User name used to login to cloud services",
        default = ''
        )
            
    num_cloud_instances: IntProperty(
            
        name = "No. nodes wanted",
        description = "Number of cloud nodes to be requested",
        default = 0,
        min = 0, #for testing without racking up a huge bill ;)
        update = num_cloud_instantes_update)
            
    num_cloud_insts_discovery: StringProperty(
            
        name = "Number of cloud instances",
        description = "the number of cloud instances currently requested",
        default = "",
            
        )
            
            
    cloud_credit: StringProperty(
        
        name = "Credit",
        description = "Credit currently held for cloud services",
        default = ""
        )
    
    renderjob_temp_dir: StringProperty(
        
        name="Temporary blend file path",
        description=" A temporary location used when crowdrender renders on the master/client",
        default = ''
        )
    
    session_path: StringProperty(
        
        name = "Session temp path",
        description= "Temp storage location for all session data",
        default =''
        
        )
    
    temp_blend_file: StringProperty(
        
        name = "Temp blend file",
        description= "Temp storage copy of the blend file",
        default =''
        
        )

    @classmethod
    def register(cls):
        """Add the crowd render properties to the current scene
        
        """
        #debug if needed
        #print(dir(cls))
        
        
        bpy.types.WindowManager.cr = PointerProperty(
            name="Crowd Render Settings",
            description="Crowd Render settings",
            type=cls
            ) 
                

    @classmethod
    def unregister(cls):
        """Remove the crowd render properties from the current scene
        
        """
        if hasattr(bpy.types.WindowManager, 'cr'):
            del bpy.types.WindowManager.cr


                
#-------------------------End of class--------------------------------------



bpy.utils.register_class(CRNodes)

def register():

    global engine_modules, address_list 
   
    address_list = (('','','',),) #initialise to null, we'll call an operator later to 
    # populate this.
    
    
    bpy.utils.register_class(CrowdRenderSceneSettings)
    bpy.utils.register_class(CrowdRenderGlobalSettings)
    bpy.utils.register_class(CrowdRenderTempProperties)
    
    bpy.types.Scene.cr_nodes = bpy.props.CollectionProperty(type = CRNodes)
    bpy.types.Scene.cr_node_index = bpy.props.IntProperty(
                                    name = "active node", 
                                    description = "index of the active node",
                                    min = 0,
                                                        )


def unregister():
    
    bpy.utils.unregister_class(CrowdRenderSceneSettings)
    bpy.utils.unregister_class(CrowdRenderGlobalSettings) 
    bpy.utils.unregister_class(CrowdRenderTempProperties)   
    bpy.utils.unregister_class(CRNodes)
    bpy.utils.unregister_class(ComputeDevices)
    bpy.utils.unregister_class(UserRenderEngineChoice)
    bpy.utils.unregister_class(CloudIssue)
    bpy.utils.unregister_class(CloudIssuesList)