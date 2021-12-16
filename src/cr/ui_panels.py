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

"""ui_panels - define Blender panels

Purpose

To present a user interface to our new render engine. Pretty simple really!

Input/Output

Again, as with the operators, there is no real input to this module. The 
output is the registration of classes that blender uses to draw its
user interface. For example, since this is a render engine, there needs
to be a panel that is drawn to show the render settings for our engine
when the user chooses to use CrowdRender as the render engine for a scene. 

How

The panels subtype of bpy.types is sub classed and extended to provide the 
necessary information for blender to draw panels in the right places, such
as the properties panel. 

Since we aim to be as least intrusive on the user experience as possible, 
we aim to re-use the panels from cycles and blender internal so that, as far
as the user is concerned, they are using those engines, but on several 
machines rather than one. 

For more information on how this is done see:

http://wiki.blender.org/index.php/Dev:2.5/Py/Scripts/Cookbook/Code_snippets/Interface#Interface


Modules Imported

Classes Exported

Exceptions Raised

Functions Exported


"""

import bpy, sys, os, time
import bpy.utils.previews
from . import settings
from . import ui_operators, utils
from . utils import timed_out
types = bpy.types

crowdrender = sys.modules[__package__]


# Load icons
global icons_dict
# Set CR panel to display start button unless the CRmain op is running
cr_running = False
cr_requesting = False #bool to indicate we're requesting nodes


    
    

class UILIST_UL_crnodes(types.UIList):
    """ menu to hold a list of hosts and accept new ones from the user """
    
        
    def __init__(self):
        types.UIList.__init__(self)
            
        
        self.icon_value_default = icons_dict["progress_" +\
                                "{0:0=2d}".format( 1 )]
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, 
                    index, flt_flag):
        """ custom drawing of the list """
        
        state = utils.states_user_sees[item.node_state]
        
        if item.node_state == utils.uploading:
            
            state_text =  state + " " + str(item.node_sync_progress) + " %"
            icon_value = icons_dict.get("progress_" +\
                                "{0:0=2d}".format(item.node_sync_progress),
                                self.icon_value_default).icon_id
            
        elif item.node_state == utils.rendering:
        
            state_text =  state + " " + str(item.node_render_progress) + " %"
            icon_value = icons_dict.get("progress_" +\
                                "{0:0=2d}".format(item.node_render_progress),
                                self.icon_value_default).icon_id
                                
        elif item.node_state == utils.downloading_results:
            
            state_text =  state + " " + str(item.node_result_progress) + " %"
            
        elif item.node_state == utils.repairing:
        
            state_text = state + " " + item.node_repair_item
            
        else:
            
            state_text =  state
            icon_value = icons_dict.get("progress_" +\
                                "{0:0=2d}".format(item.node_sync_progress),
                                self.icon_value_default).icon_id
            
        
        # 'DEFAULT' and 'COMPACT' layout types should usually use the same draw code.
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
        
            
            
            row = layout.row(align=True)
            
            #show inactive nodes as greyed out, they can be inactive either 
            # by the user deciding they should not render, or by them not having
            # posted to discovery yet.
            
            row.active = item.node_render_active and \
                item.node_active
                
            split = row.split(factor = 0.6)
            
            split.prop(item, "name", text="", emboss=False)
            split.label(text =state_text)
            
            
            ## BUTTONS FOR EACH NODE CONNECT/EXCLUDE RENDER/SETTINGS
            # We only show the connect button, no point showing the others until 
            # the node is active
            
            op = row.operator("crowdrender.show_node_reports", icon="INFO",
                            text = "", emboss = False).node_uuid = item.node_uuid          
                            
                # node = op.nodes.add()
#                 node.reports = item.reports
                            # \
#                               [{  'name':item.name,
#                         'cr_version': item.cr_version,
#                         'node_address':item.node_address,
#                         'node_state':item.node_state,
#                         'node_uuid':item.node_uuid,
#                         'node_access_key':item.node_access_key,
#                         'node_image_coords':item.node_image_coords,
#                         'node_local':item.node_local,
#                         'node_sync_progress':item.node_sync_progress,
#                         'node_render_progress':item.node_render_progress,
#                         'node_result_progress':item.node_result_progress,
#                         'node_repair_item':item.node_repair_item,
#                         'node_active':item.node_active,
#                         'node_render_active':item.node_render_active,
#                         'node_A_manual':item.node_A_manual,
#                         'node_A_auto':item.node_A_auto,
#                         'node_tile_x':item.node_tile_x,
#                         'node_tile_y':item.node_tile_y,
#                         'compute_devices':[
#                             {'name':device.name,
#                              'use':device.use,
#                              'id':device.id,
#                              'type':device.type} for device in item.compute_devices],
#                         'compute_device':item.compute_device
#                     } ]
                    
            row.operator("crowdrender.connect_remote_server", 
                            #icon_value=connect_icon_value, 
                            icon="LINKED",
                            text ="", emboss = False).node_name = item.name
                            #,icon_value = icon_value) #removed animated 
                            # icons as they were very glitchy, they can 
                            # be displayed again by uncommenting the first 
                            # line above.
            if  item.node_active:                   
                row.prop(item, "node_render_active",
                    icon='SCENE', icon_only=True, toggle=True, emboss=False)
            
                row.operator("crowdrender.node_settings_dialog",
                    icon='SETTINGS', emboss=False).node_name=item.name
            
        # 'GRID' layout type should be as compact as possible (typically a single icon!).
        elif self.layout_type in {'GRID'}:
            pass



class CrenderButtonsPanel():
    """Define a render engine subclassed from bpy.types.RenderEngine
    
    Documenetation for the bpy.types.RenderEngine is here:
    
    http://wiki.blender.org/index.php/Dev:2.6/Source/Render/RenderEngineAPI
    
    """
    
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    @classmethod
    def poll(cls, context):
        rd = context.scene.render
        return True#rd.engine == crowdrender.package_name



                  
class RENDER_PT_network_panel(CrenderButtonsPanel, bpy.types.Panel):
    """TODO
    
    """
    
    bl_label = "Crowdrender"
    bl_options = {'DEFAULT_CLOSED'}
    
    TEXT = 0
    ICON = 1
    OPERATOR = 2
    
    
    def __init__(self):
    
        self.start_time = time.perf_counter()
   
        bpy.types.Panel.__init__(self)
        
        
            
        self.icon_value_default = icons_dict["progress_" +\
                                    "{0:0=2d}".format( 1 )]
    
    
    def draw(self, context):
    
        layout = self.layout
        
        global cr_running
        
        #split = layout.split(percentage=0.5)
        
        crowd_render_scene_settings = context.scene.crowd_render
        cr_temp = context.window_manager.cr
                
        box = layout.box()
        
        row = box.row(align=True)
        
        if not cr_running:
        
            row.operator("crowdrender.main", text = "START", icon = "INFO")
        
        else:
        
            row = box.row(align=False)
            col = row.split(factor = 0.90, align =False)
            col.label(text="Render Controls")
            col.operator("crowdrender.open_help", text="", icon="QUESTION")
            
            row = box.row(align = True)
            
            row.prop(context.scene.crowd_render, "render_engine")
            
            row = layout.row(align=True)
            
            layout.separator()
            
            box = layout.box()
            box.label(text = "Render Nodes")
            box.operator("crowdrender.show_load_balancer", icon = "SETTINGS")
            box.prop(context.scene.render.image_settings, "exr_codec", )
            
            #LOCAL NODE
            local_node = context.scene.crowd_render.local_node
            local_m_percent_complete = round(local_node.node_render_progress)
            local_m_state = state = utils.states_user_sees[local_node.node_state]
            local_m_icon_value = icons_dict.get("progress_" +\
                                    "{0:0=2d}".format(local_m_percent_complete),
                                    self.icon_value_default).icon_id
                            
            if local_node.node_state == utils.rendering:                      
                local_m_display_text = local_m_state + " " + \
                                    str(local_m_percent_complete) + "%"
            else:
                local_m_display_text = local_m_state
                            
            #draw local machine/node's stats just above the prop window of 
            #all the other nodes
    
            row = box.row(align = True)
            row.active = context.scene.crowd_render.local_node.node_render_active
            row.label(text = "this machine: ")
            row.label(text =local_m_display_text) #, icon_value = local_m_icon_value)
            op = row.operator("crowdrender.show_node_reports", icon = "INFO", 
                emboss = False, text='').node_uuid = local_node.node_uuid
            row.prop(context.scene.crowd_render.local_node, "node_render_active",
                icon='SCENE', emboss=False, icon_only=True, toggle=True)
            row.operator("crowdrender.node_settings_dialog",
                    icon='SETTINGS', emboss=False).node_name="local"
                # animated icons disabled as they
                # were too glitchy
        
            #REMOTE MACHINES - layouts for button and label
        
            row = box.row(align=True)
            col = row.column(align=True)
        
            node_list_row = col.row(align=True)   
            node_list_row.template_list("UILIST_UL_crnodes", #id of type of list
                            "", #list_id
                            context.scene, #dataptr
                            "cr_nodes", #propname of the list data
                            context.scene, # dataptr, points to active index
                            "cr_node_index", #propname of the active index
                            item_dyntip_propname = "node_address", #propname for tooltip
                            rows = 5, 
                            maxrows = 0,
                            columns = 3)
                            
            row_ops_1 = col.row(align=True)
                            
            #col = row_ops_1.column(align=True)                    
            row_ops_1.operator("crowdrender.add_cr_node", icon='ADD', text="")
            row_ops_1.operator("crowdrender.rem_cr_node", icon='REMOVE', text="")
        
            #row_ops_2 = layout.row(align=True)
        
            #col2 = row_ops_1.column(align=True)
            row_ops_1.operator("crowdrender.connect_remote_server", 
                      icon="LINKED",#  icon_value=connect_icon_value, 
                        text ="Connect").node_name = ""
                             
            resync_props = row_ops_1.operator("crowdrender.resync_remote_machine", 
                      icon="FILE_REFRESH",#  icon_value=resync_icon_value,
                        text = "Resync")
            
            resync_props.node_name = ""
            
            layout.separator()
            layout.prop(crowd_render_scene_settings, "use_cloud_rendering")
        
            if crowd_render_scene_settings.use_cloud_rendering:
        
                box = layout.box()
                row = box.row(align=True)
                
                col1 = row.column(align=True)
                col2 = row.column(align=True)
                col3 = row.column(align=True)
            
                col1.label(text = "Crowdrender Cloud")
                
                col2.label(text = "$" + cr_temp.cloud_credit)
                # grey out the issues panel button if there's nothing in there
                if len(cr_temp.cloud_system_issues): col3.active = True
                else: col3.active = False
                
                op = col3.operator("crowdrender.show_discovery_issues", icon="ERROR",
                            text = "", emboss = False)
            
                if not cr_temp.logged_in:
                    
                    box.prop(cr_temp, "user_name")
                    box.prop(cr_temp, "password")
                    box.operator("crowdrender.crowdrender_login")
            
                else:
                    
                    num_inst_row = box.row(align=True)
                    num_inst_row.prop(cr_temp, "num_cloud_instances")
                    if cr_requesting:
                        num_inst_row.label(
                            text = "Requesting " +\
                                 cr_temp.num_cloud_insts_discovery)
                    else:
                        num_inst_row.label(
                            text = "Ready to request: " +\
                                 cr_temp.num_cloud_insts_discovery
                                        )
                    start_stop_row = box.row(align=True)
                    start_stop_row.operator("crowdrender.start_instance_request",
                                            emboss = not cr_requesting)
                    
                    start_stop_row.operator("crowdrender.stop_instance_request")
                    logout_row = box.row(align = False)
                    logout_row.operator('crowdrender.crowdrender_logout')
                    
                    
        
        if timed_out(self.start_time, 1.0):#Configure our connect, cancel button based on client's status
            
            cr_running = False
            self.start_time  = time.perf_counter()

                
                
            


                    
def register():
    
    global icons_dict, connect_icon_value, disconnect_icon_value, resync_icon_value
    
    icons_dict = bpy.utils.previews.new()
    addon_path = __file__.split(crowdrender.package_name)[0] 
        
    

    connect_icon_path = os.path.join(addon_path,"crowdrender/icons/connect.png")
    disconnect_icon_path = os.path.join(addon_path,"crowdrender/icons/disconnect.png")
    resync_icon_path = os.path.join(addon_path,"crowdrender/icons/resync.png")

    icons_dict.load("connect_icon", connect_icon_path, 'IMAGE')
    icons_dict.load("disconnect_icon", disconnect_icon_path, 'IMAGE')
    icons_dict.load("resync_icon_path", resync_icon_path, 'IMAGE')

    connect_icon_value = icons_dict["connect_icon"].icon_id
    disconnect_icon_value = icons_dict["disconnect_icon"].icon_id
    resync_icon_value = icons_dict["resync_icon_path"].icon_id

    for i in range(1, 101):
        path = os.path.join(addon_path, "crowdrender/icons/progress/", "{0:0=4d}".format(i)+".png")
        icons_dict.load("progress_"+ "{0:0=2d}".format(i), path, 'IMAGE')
    
    #Register classes
    bpy.utils.register_class(UILIST_UL_crnodes)
    bpy.utils.register_class(RENDER_PT_network_panel)
    



def unregister():
    try:
        bpy.utils.previews.remove(icons_dict)
    except KeyError:
        print("Handled KeyError on removing icon previews")
    
    try:
        bpy.utils.unregister_class(UILIST_UL_crnodes)
    except RuntimeError:
        print("handled RuntimeError on unregistering UIList class")
    try:    
        bpy.utils.unregister_class(RENDER_PT_network_panel)
    except RuntimeError:
        print("handled RuntimeError on unregistering Panel class")
    
    
    
    

                  