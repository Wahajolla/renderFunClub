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
rules - mappings and algorithms for creating a hash tree from a data structure.

Purpose

The Crowd Render kernel is designed to be application agnostic. To be 
able to 'know' how to parse a data structure, the hash_tree classes 
expect a CRRules object which implement methods with specific names as
part of our API. 

How

Each application will have its own implementation of CRRules, however there
are must have items that are part of the API and crucial for proper function.

    update, parse, get_name and hash functions: 
    These four functions are expected from 
    the CRRules object in the crowdrender kernel. Their definitions are
    given below. This module can serve as a template for external dev's
    who wish to use the CR platform to perform parallel programming tasks. 
    
 

Classes Exported - CRRules

Errors Raised - None (as yet)

Functions Exported - None

"""

import bpy, cycles
from decimal import *
from mathutils import Vector, Color, Quaternion, Euler
from . import utils
from . import attributes
from . utils import l_sep, handle_generic_except, crowdrender_session_metadata
from bpy.types import bpy_prop_collection

####  CREATE CRASH LOGS #####
import faulthandler, os

fault_text_file_path = os.path.expanduser("~") +\
     os.path.normpath("/cr/logging/rules.txt")

if os.path.exists(fault_text_file_path):
    fault_text_file = open(fault_text_file_path, "wb")
else:
    utils.mkdir_p(os.path.split(fault_text_file_path)[0])
    fault_text_file = open(fault_text_file_path, "wb")

faulthandler.enable(file = fault_text_file)

previously_selected = utils.previously_selected_int
dictionary = utils.dictionary
last = utils.last
naughty_modals =    ['VIEW3D_OT_select_circle',
                     'VIEW3D_OT_select_border']

inf = float('inf')

def get_blender_executable():
    """ return a path to the executable that is running the python interpreter
    
    Description:
        Python has two locations where it stores information about the currently running 
        executable, sys.executable, and also sys.argv. Usually sys.executable is reliable
        however in certain circumstances it can be wrong as it will in some
        contexts query the PATH env var to find the python exe that is running. If an 
        application changes this var during run time then sys.executable is wrong.
        
         """
         
         
    exe_path = bpy.app.binary_path
         
    
        
    return exe_path

def get_cycles_devices():
    
    cycles = bpy.context.preferences.addons['cycles']
    
    optix_devs = cycles.preferences.get_devices_for_type('OPTIX')
    cuda_devs = cycles.preferences.get_devices_for_type('CUDA')
    opencl_devs = cycles.preferences.get_devices_for_type('OPENCL')
    cpu_devs = cycles.preferences.get_devices_for_type('CPU')
    
    devices = set(optix_devs)
    devices.update(set(cuda_devs))
    devices.update(set(opencl_devs))
    devices.update(set(cpu_devs))
    
    cycles_devices = [
        (device.name, 
          device.id, 
          device.type, 
          device.use)
         for device in devices]
    
    return cycles_devices
    
def get_compute_devices():
    """Return a serializable list of compute devices
    
    Arguments: None
                        
    returns: A serializable list of compute devices for this machine.
    
    Description
    This method creates a serializable list containing name, type and 
    use for each of this machines compute devices and returns it.
    
    Changed to use _cycles.available_devices
    ( (name, type, id) )
    """
    cycles = bpy.context.preferences.addons['cycles']
    
    optix_devs = cycles.preferences.get_devices_for_type('OPTIX')
    cuda_devs = cycles.preferences.get_devices_for_type('CUDA')
    opencl_devs = cycles.preferences.get_devices_for_type('OPENCL')
    cpu_devs = cycles.preferences.get_devices_for_type('CPU')
    
    ##ADD OPTIX DEVICES
    devices = [{'name':device.name, 
         'type':'OPTIX',
         'id':device.id,
         'use':True } \
          for device in optix_devs]
    ##ADD CUDA DEVICES
    devices.extend(
        [{'name':device.name, 
         'type':'CUDA',
         'id':device.id,
         'use':True } \
          for device in cuda_devs]
    )
    ##ADD OPENCL DEVICES
    devices.extend(
        [{'name':device.name, 
         'type':'OPENCL',
         'id':device.id,
         'use':True } \
          for device in opencl_devs]
    )
    ##ADD CPU DEVICES
    devices.extend(
        [{'name':device.name, 
         'type':'CPU',
         'id':device.id,
         'use':True } \
          for device in cpu_devs])
    # 'use' option set to True as default, the user can change this if desired
    
    
    return devices
        

def get_blender_version():
    
    return "_".join(map(str, bpy.app.version))
    
def get_base_app_version():
    
    return get_blender_version()
    
def get_session_uuid(data):
    """ Return the sesssion uuid or raise
    """
    
    #legacy support for older scenes using this 
    cr_old = data.objects.get(".__cr__", None)  
    cr = data.texts.get(crowdrender_session_metadata, None)
    
    if cr_old is not None: 
        session_uuid = cr_old.get('cr').to_dict()['session_uuid']
    
    elif cr is not None: session_uuid = cr.cr.session_uuid
    else:
        session_uuid = ''
    
    return session_uuid


def create_session_uuid():
    
    import uuid
    

    #danger! We're loading the default file, do not attempt to load
    # the uuid if its been stored.
    cr_uuid = uuid.uuid4()
    
    #create settings object
    bpy.data.texts.new(crowdrender_session_metadata)
    bpy.data.texts[
        crowdrender_session_metadata].cr.session_uuid = str(cr_uuid)
    
   
            
    
class CRTypeDummy:
    """ Used as a dummy type in building the _dict mapping for blender 
    """
    pass

class CRRules:
    """ Implements a system for a CRHashTreeNodes to parse a data structure
    
    Public Methods:
    
    
    update - detect tags in changed data, call hashing algorithms, 
        parsing algorithms
    parse - search a node for children and call the kernel's insert_child 
        method.
    iterate - return an iterable list of attributes from an object that 
        doesn't support looping (all plain vanilla objects have this 
        property, only collections with an __iter__ attribute can be
        looped over without alteration. 
        
    get_name - Return a name attribute from the data. The data has to 
        have this attribute and the developer must write this method to
        return this attribute as a string.
        
    hash - Returns an integer representing the hash value of the data it 
        is given. 
    
    Public data variables:
    
        static variables:
        black_list - names of attributes you don't want to hash
        default_name - a default name, why? I have no idea
        child_data - int: index to the internal mapping _dict, returns the 
        dictionary which contains the potential children of the current node.
        child_type - int: index to the internal mapping _dict, gives the
            position of a child's data type.
        
        Instance variables:
        data - ref to this node's data
        type - the class that this node's data is derived from.
    
    """
    global _dict, default_name, child_data \
        , child_type, _hash_functions, _dict_of_types, _dict_top_level_dblks
    
    
    
    cr_allowable_types = (int, str, float, complex, bool,
                            Color, Vector, Euler, Quaternion,
                            bpy.types.bpy_prop_array)
    
                                
                           
    _dict = {      bpy.types.BlendData:
        ('data', {'scenes':(bpy.types.BlendDataScenes, ) } ,) ,
                   bpy.types.BlendDataScenes:
        ('scenes', {'Scene':( bpy.types.Scene, ) } ,) ,
                   bpy.types.Scene:
        ('Scene', {'objects':( bpy.types.SceneObjects, ),
                  'world':( bpy.types.World,),
                  'render':( bpy.types.RenderSettings,),
                  'cycles':( getattr(cycles.properties, 'CyclesRenderSettings', None),),
                  'cycles_curves':(getattr(cycles.properties, 
                                    'CyclesCurveRenderSettings', None),),
                  'view_layers':(bpy.types.ViewLayer,)
                    } , ),
                  #'node_tree':( bpy.types.CompositorNodeTree, ) } , ),
                  bpy.types.ViewLayer:
        ('view_layer', {'cycles':(getattr(cycles.properties, 
                                    'CyclesRenderLayerSettings', None),)} ,) ,
                  bpy.types.RenderSettings:
        ('RenderSettings', {'layers':(getattr(bpy.types, 'RenderLayers', None),)} , ),
                  getattr(bpy.types, 'RenderLayers', CRTypeDummy):#need a dummy type:
        ('layers', {'layer':(getattr(bpy.types, 'SceneRenderLayer', None), )} , ), 
                  getattr(bpy.types, 'SceneRenderLayer', CRTypeDummy):
        ('layer', {'cycles':(getattr(cycles.properties, 
                            'CyclesRenderLayerSettings', None), )} ,),          
                  bpy.types.World:
        ('world', {'node_tree':(bpy.types.ShaderNodeTree,),
                    'cycles':(getattr(cycles.properties, 
                            'CyclesWorldSettings', None),) } , ),
                   # bpy.types.World: #commented out due to issue with as_pointer 
                   # returning the same value for world, light_settings and Mist settings
#         ('world', {'light_settings':(bpy.types.WorldLighting, ),
#                   'mist_settings':(bpy.types.WorldMistSettings,) } , ),
                   bpy.types.CompositorNodeTree:
        ('node_tree', {'nodes':(bpy.types.Nodes,) }, ),
                   bpy.types.Nodes:
        ('nodes', {'CompositorNodeViewer':(bpy.types.CompositorNodeViewer,),
                   'CompositorNodeAlphaOver':(bpy.types.CompositorNodeAlphaOver,),
                   'CompositorNodeBlur':(bpy.types.CompositorNodeBlur,),
                   'CompositorNodeComposite':(bpy.types.CompositorNodeComposite,),
                   'CompositorNodeMixRGB':(bpy.types.CompositorNodeMixRGB,),
                   'CompositorNodeCurveRGB':(bpy.types.CompositorNodeCurveRGB,),
                   'CompositorNodeRLayers':(bpy.types.CompositorNodeRLayers,),
                   'CompositorNodeFilter':(bpy.types.CompositorNodeFilter,),
                   'ShaderNodeBsdfGlass':(bpy.types.ShaderNodeBsdfGlass,),
                   'ShaderNodeBsdfPrincipled':(getattr(bpy.types, 
                        'ShaderNodeBsdfPrincipled', None), ),
                   'ShaderNodeOutputMaterial':(bpy.types.ShaderNodeOutputMaterial,),
                   'ShaderNodeBsdfDiffuse':(bpy.types.ShaderNodeBsdfDiffuse,),
                   'ShaderNodeFresnel':(bpy.types.ShaderNodeFresnel,),
                   'ShaderNodeBsdfGlossy':(bpy.types.ShaderNodeBsdfGlossy,),
                   'ShaderNodeMixRGB':(bpy.types.ShaderNodeMixRGB,),
                   'ShaderNodeMixShader':(bpy.types.ShaderNodeMixShader,),
                   'ShaderNodeBsdfTranslucent':(bpy.types.ShaderNodeBsdfTranslucent,),
                   'ShaderNodeBsdfHair':(bpy.types.ShaderNodeBsdfHair,),
                   'ShaderNodeRGB':(bpy.types.ShaderNodeRGB,),
                   'ShaderNodeHueSaturation':(bpy.types.ShaderNodeHueSaturation,),
                   'ShaderNodeGroup':(bpy.types.ShaderNodeGroup,),
                   'ShaderNodeValToRGB':(bpy.types.ShaderNodeValToRGB,),
                   'ShaderNodeBsdfTransparent':(bpy.types.ShaderNodeBsdfTransparent,),
                   'ShaderNodeTexGradient':(bpy.types.ShaderNodeTexGradient,),
                   'ShaderNodeMapping':(bpy.types.ShaderNodeMapping,),
                   'ShaderNodeTexCoord':(bpy.types.ShaderNodeTexCoord,),
                   'ShaderNodeEmission':(bpy.types.ShaderNodeEmission,),
                   'ShaderNodeNewGeometry':(bpy.types.ShaderNodeNewGeometry,),
                   'ShaderNodeTexImage':(bpy.types.ShaderNodeTexImage,),
                   'ShaderNodeInvert':(bpy.types.ShaderNodeInvert,),
                   'ShaderNodeSeparateRGB':(bpy.types.ShaderNodeSeparateRGB,),
                   'ShaderNodeUVMap':(bpy.types.ShaderNodeUVMap,),
                   'ShaderNodeBackground':(bpy.types.ShaderNodeBackground,),
                   'ShaderNodeTexEnvironment':(bpy.types.ShaderNodeTexEnvironment,),
                   'ShaderNodeOutputWorld':(bpy.types.ShaderNodeOutputWorld,),
                   'ShaderNodeRGBCurve':(bpy.types.ShaderNodeRGBCurve,),
                   'ShaderNodeMath':(bpy.types.ShaderNodeMath,),
                   'ShaderNodeRGBToBW':(bpy.types.ShaderNodeRGBToBW,),
                   'ShaderNodeLayerWeight':(bpy.types.ShaderNodeLayerWeight,),
                   'ShaderNodeBsdfRefraction':(bpy.types.ShaderNodeBsdfRefraction,),
                   'ShaderNodeTexVoronoi':(bpy.types.ShaderNodeTexVoronoi,),
                   'ShaderNodeTexWave':(bpy.types.ShaderNodeTexWave,),
                   
                   }, 
                   ),
                   bpy.types.SceneObjects:
        ('objects', {'Object':(bpy.types.Object,) }, ),
                   bpy.types.Object:
        ('Object', {'data':(bpy.types.Mesh,bpy.types.Camera,bpy.types.AreaLight,
                            bpy.types.PointLight,#bpy.types.HemiLight,
                            bpy.types.SpotLight,bpy.types.SunLight),
                    #'animation_data':(bpy.types.AnimData,),
                    'material_slots':(bpy.types.MaterialSlot,),
                    'modifiers':(bpy.types.ObjectModifiers,)}, ),
                    bpy.types.Mesh:
        ('data', {'animation_data':(bpy.types.AnimData,)}),
                  # 'materials':(bpy.types.IDMaterials,),
#                   'vertices':(bpy.types.MeshVertices,),
#                   'polygons':(bpy.types.MeshPolygons,),
#                   'edges':(bpy.types.MeshEdges,)}, ),
                    # bpy.types.MeshVertices:
#         ('vertices', {'vertex':(bpy.types.MeshVertex,) },),
#                     bpy.types.MeshEdges:
#         ('edges', {'edge':(bpy.types.MeshEdge,) },), 
#                     bpy.types.MeshPolygons:
#         ('polygons', {'polygon':(bpy.types.MeshPolygon,) },),
                    bpy.types.ObjectModifiers:
        ('modifiers', {'SubsurfModifier':(bpy.types.SubsurfModifier,) },),
                    bpy.types.MaterialSlot:
        ('material_slots', {'material':(bpy.types.Material,) },),
                    bpy.types.IDMaterials:
        ('materials', {'Material':(bpy.types.Material,) },) ,
                    # bpy.types.Material:
#         ('Material', {'texture_slots':(bpy.types.MaterialTextureSlots,),
#                         'node_tree':(bpy.types.ShaderNodeTree,) },) ,
#                     bpy.types.MaterialTextureSlots:
#         ('texture_slots', {'TextureSlot':(bpy.types.MaterialTextureSlot,) }, ) ,
#                     bpy.types.MaterialTextureSlot:
#         ('texture_slot', {'Texture':(bpy.types.Texture,),
#               'ImageTexture':(bpy.types.ImageTexture,),
#               'EnvironmentMapTexture':(bpy.types.EnvironmentMapTexture,), 
#               'CloudsTexture':(bpy.types.CloudsTexture,) }, ) ,
                    bpy.types.CurveMapping:
        ('curves', {'curves':(bpy.types.CurveMap,) },),
                    bpy.types.CurveMap:
        ('curve', {'points':(bpy.types.CurveMapPoints,) },),
                    bpy.types.CurveMapPoints:
        ('points', {'point':(bpy.types.CurveMapPoint,) },),
                    bpy.types.ShaderNodeTree:
        ('node_tree', {'nodes':(bpy.types.Nodes,) }, )
        
                      }
                      
    children_types = 1

    bl_types = dir(bpy.types)

    socket_types = list()
    new_dict = {}

    for bl_type in bl_types:
        if 'NodeSocket' in bl_type:
            node_socket = getattr(bpy.types, bl_type)
            socket_types.append(node_socket)
    
    
    #print(socket_types)

    socket_map = {}


    for classes in _dict: #(keys are classes)

        if classes is bpy.types.Nodes:
    
            nodes = _dict[classes][children_types]

            for node_type in nodes.values():
            
                socket_list = list()
        
                for socket_type in socket_types:
                
                    socket_list.append(socket_type)
            
                socket_map['inputs'] = socket_list
                socket_map['outputs'] = socket_list
                #need to add curve mapping here as well so its
                # availablef to all nodes, easier than 
                # going back and manually editing the _dict 
                # structure to only give it to those nodes that
                # need it.
                socket_map['mapping'] = (bpy.types.CurveMapping,)
                
                new_entry = ('inputs', socket_map)
                            
                            
                new_dict[node_type[0]] = new_entry

    _dict.update(new_dict)
                      
    _not_indexable = {}
          
          
    _dict_of_types = {  bpy.types.Object:
        bpy.types.Scene, 
                        bpy.types.Scene:
        bpy.types.BlendData}
                        # bpy.types.World:
        # bpy.types.SceneObjects, 
                        # bpy.types.RenderSettings:
        # bpy.types.SceneObjects,
                        # bpy.types.Mesh:
        # bpy.types.Object,
                        # bpy.types.AnimData:
        # bpy.types.Object,                
                        # bpy.types.ObjectModifiers:
        # bpy.types.Object, 

    _dict_top_level_dblks = { 'world':bpy.types.World, 
                              'render_settings':bpy.types.RenderSettings,
                              'node_tree':bpy.types.CompositorNodeTree }
           #'scene':bpy.types.Scene, need to add an exception 
           # to processing scene recursively since we'd 
           # effectively process all objects in the 
           # scene which is not what we want. 
           
    salts = (59969537, 7778777, 29986577, 16769023)
                              
    
    def _hash_vector(self, data):

        fourD_data = data.to_4d()
        
        return ((self._hash_float(fourD_data.x) * 59969537) ^ (self._hash_float(fourD_data.y) * 7778777) ^\
            (self._hash_float(fourD_data.z) * 29986577)^ (self._hash_float(fourD_data.w) * 16769023))
               #Insert maximum float value? here
               
    def _hash_prop_array(self, data):
        
        # where we have data that represents orthogonal spaces, bhwa ha haaa! Sorry, 
        # started talking like the nutty professor, so, data that has dimensions
        # , like a coordinate system,
        # needs to have a salt applied to each dimension, otherwise its easy to have
        # situations where the hash value isn't unique for a unique situation, i.e.
        # imagine 3d coords, x,y,z. If we just add the values together to form a 
        # hash, then 0 0 1, 0 1 0 and 1 0 0 end up giving the same answer, but the 
        # data is actually different since there is meaning in the position of the numbers
        # not just their magnitude. So we apply the salts to each dimension to make sure
        # that 0 0 1 does not has to the same value as 1 0 0 and 0 1 0.
        
        if len(data) <= 4:
        
            hash = 0
        
            for i in range(0, len(data)):
            
                hash_func = self._hash_functions[type(data[i])]
            
                hash ^= hash_func(data[i]) * self.salts[i]
                
            return hash
        elif len(data) <=20:
            
            hash = 0
            
            for i in range(0, len(data)):
            
                hash_func = self._hash_functions[type(data[i])]
                
                #hash that boolean using an incremental power of 2 to the i
                hash += 2**i * hash_func(data[i])
                
            return hash    
                    
        else:
            # interesting choice I admit, but, bpy_prop_arrays are used for storing 
            # pixels, which would be a bad thing to try and has since there are
            # potentially millions of them. So, either we stick to hashing what we 
            # know, vectors like colour, location and so on, or we open ourselves to 
            # hashing any length of array and deal with the consequences. 
            return 0
        
                
            
        
    def _hash_color(self, data):
        return ((self._hash_float(data.r) * 59969537) ^ (self._hash_float(data.g) * 7778777)  ^\
            (self._hash_float(data.b) * 29986577))
        # Had abs around color. Not entirely sure why but we may need to add it back if things go bad
    def _hash_quaternion(self, data):
        return ((self._hash_float(data.x) * 59969537) ^ (self._hash_float(data.y) * 7778777) ^\
            (self._hash_float(data.z) * 29986577) ^ (self._hash_float(data.w) * 16769023))
        
    def _hash_euler(self, data):
        return ((self._hash_float(data.x) * 59969537) ^ (self._hash_float(data.y) * 7778777) ^\
            (self._hash_float(data.z) * 29986577)) #19496742305195398000000000000000000000000
        
    def _hash_builtin(self, data):
                 
        return int(data)
        #We can't simply int types like float since int(0.000001123123) 
        # gets converted to 0 meaning we lose all information about 
        # this data.
        
    def _hash_complex(self, data):
        
        return (self._hash_float(data.real) * salt[0] ^ self.hash_float(data.imag) *\
            salt[1])
    
    def _hash_float(self, data):
        return (int(Decimal(data) * Decimal(1e17)))
     
    def _hash_string(self, data):
        temp = ''
        slist = [str(ord(c)) for c in data]
        temp = "".join(slist)
        if temp == '':
            return 0
        return abs(int(temp))
        
    def _hash_unhashable(self, data):
        return 0
    
    # built ins are  int, bool, float, str, complex, Vector, Color
    
    def func_map(self):
        _hash_functions = {int:self._hash_builtin, bool:self._hash_builtin,
                       float:self._hash_float, str: self._hash_string,
                       complex:self._hash_complex, Vector:self._hash_vector, 
                       Color:self._hash_color, Quaternion: self._hash_quaternion,
                       Euler: self._hash_euler, 
                       bpy.types.bpy_prop_array:self._hash_prop_array
                       }#, un_hashable:_hash_unhashable
        
        return _hash_functions
        
    default_name = 0
    child_data = 1
    child_attr_name = 1
    child_type = 0
    
    def __init__(self):
    
        #Internal data variables
        
        self.black_list = attributes.black_list
        self._dict = _dict
        self.default_name = default_name
        self.child_data = child_data
        self.child_type = child_type
        # self.build_dict()
        # self.build_hash_rules()
        self._hash_functions = self.func_map()
        self.op_handlers = self.op_handler_map()
        self.bl_id_2_operator = self.op_blidname_operator()
        self.last_mode = bpy.context.mode
        
    def get_ref(self, data):
        """ tries to get a pointer to the data using the 'as_pointer' method.
        
        args:
        data: reference to the data
        
        returns:
        integer representing the pointer to the data
        
        errors:
        will raise an exception when the data is missing the 'as_pointer' 
        attribute
        
        """
        
        if hasattr(data, 'as_pointer'):
            return data.as_pointer()
        else:
            raise
       
        
    def get_type(self, data):
        if hasattr(data, 'bl_rna'):
            return type(data.bl_rna)
        else:
            return type(data)
            
    def get_operators(self):
        """ set dictionary of operators based on bl_idname
        
        Creates and sets a dictionary that contains the operators we'll
        process. The key of the dictionary is the bl_idname of the operator
        and the value is the attribute name of the function or method of the 
        bpy.ops module. E.g. OBJECT_OT_duplicate is a key to 'duplicate' 
        which can then be used to return the method 'duplicate()' from the 
        bpy.ops.object module
             
        """
        pass
            
    def get_uuid(self, data):
        """
        return a unique UUID within this session based on name and object type.
    
    
        """
        name = ''
        index = ''
        
        #TODO, there is a bug here. When you get the uuid of a data block 
        # that doesn't have the name attribute, the function returns the
        # string representation of the object, however this includes the
        # objects memory address which of course is unique to the machine 
        # and so the uuid generated on the servers will be different, causing
        # an error (or unhandled exception as the current code stands)
        #FIXED! New code below now looks for alternatives to the name attribute
        # and does not include a string rep of the object if name or other 
        # attributes can't be found. 
    
        # Get the name of the attribute, if it doesn't have a 'name'
        # attribute, get the string representation of the object.
            
        if hasattr(data, 'identifier'):
            
            name = getattr(data, 'identifier')
        
        elif hasattr(data, 'name'):
            
            name = getattr(data, 'name')
                    
        elif hasattr(data, 'index'):
            
            index = getattr(data, 'index')
            
        
        
        
        #name = getattr(data, 'name', str(data))
    
        # Get a string representing the objects type
        if hasattr(data, 'bl_rna'):
            
            data_type = getattr(data.bl_rna, 'identifier')
            
        else:
            data_type = str(type(data))
    
        return name + str(index) + '_' + data_type
        
        
        
    # @utils.func_time    
    def get_attribs(self, data):
        """ returns a dict of all the attributes of the data not in black_list 
        
        Methodology:
        
        This method, builds a python dictionary containing refs to all 
        attributes of the data that are not in the black_list. This is then
        used in the hashing of the node to ensure that hashing is efficient. 
        
        arguments: data (py object), the input data, can be a variety of types
        return value: None
        side effects: 
        exceptions raised: None
        restrictions: Unknown
        """
        
        attribs = {}
        #print(data)
        if type(data) in attributes.attributes_map:
            names =  attributes.attributes_map[type(data)]
        else:
            names = set(dir(data)) - self.black_list
            
        #EXCEPTIONS______________________________________
               
        # only allow attributes we can send via json or hash and that are
        # not read-only. This step is included 
        # to remove attributes that would otherwise cause problems like functions,
        # non hashable or serializable types that are not yet in the black list or
        # can't be put in the black list cause they are dynamic. 
         
        # attribs = {name:getattr(data, name, None) for name in names \
            # if isinstance(getattr(data, name, None), self.cr_allowable_types) and \
             # not data.is_property_readonly(name) } 
        
        for name in names:
            
            if isinstance(getattr(data, name, None), self.cr_allowable_types) and \
                not data.is_property_readonly(name):
                
                attribs[name] = getattr(data, name, None)             
            
                
        return attribs
        
    
    # @utils.func_time                  
    def parse(self, node_data):
        """ matches nodes according to the _dict object and inserts child nodes.
        
        methodology:
        
        This method uses the _dict object to parse the data structure in 
        blender. It aims to find all objects of interest and create a node 
        for them in the hash_tree. 
        
        The approaches employed are context specific in that the code will
        search for child objects based on the type of the data the current 
        node represents (see the mapping in the build_dict() method.
        
        The code uses two approaches to searching for children which 
        correspond to the information stored in _dict. 
        
        The first approach is to look for a default name such as 'data', 
        'scenes' or 'objects'. These correspond to collections or other 
        types that don't change their name during a session and are 
        stable over the development life of blender. 
        
        The second approach is to look for a data type that matches the 
        potential list of children for the current node data type. This is
        used in situations where the object of interest has its name assigned
        dynamically at run time. A good example of this is an object (not an 
        object in the programming sense, but a bpy.types.Object type).
        An object can be added at any time by the user and the name of the 
        object is assigned dynamically. The name can also be changed by the
        user. Because of this, we can't know what the name of the object 
        will be, we cannot use a default name, so instead we use the data
        in the 'Child's default name' field of the _dict. 
        
        arguments: node_data (type unknown till runtime), 
                        insert_child_node (CRHashTreeNode.insert_child_node)
        return value: None
        side effects: Calls the CRHashTreeNode.insert_child_node method.
        exceptions raised: None
        restrictions: Unknown
        
        """
        
        # if node_data in hash_tree.nodes:
            # insert_child_node(hash_tree.nodes[node_data])
            # return
        
        # get the type of the data contained in the current HT node. We
        # use bl_rna since this will always contain the correct type. 
        # Collections are all of bpy_prop_collection type and hence
        # don't give us any information about what is stored in the
        # collection. Each collection does have a bl_rna attribute, however,
        # which gives the type of the data in the collection. 
        
        if bpy.app.debug:
            print('looking for children in :', node_data)
        
               
        _type = type(node_data.bl_rna)
        
        # if the type is in our mappings dictionary, proceed, otherwise
        # skip, there are no more objects of interest from this point on.
        
        
        child_data = self.child_data 
        _dict = self._dict
        
        ret = []
        
        
        if _type in _dict:
            
            # based on the _type of the data, look through each child data
            # entry in _dict and try to find some object in the node's 
            # data that matches.
                                              
                                            
            for attr_name in _dict[_type][child_data]:
                                        
                child_node = getattr(node_data, attr_name, None)
                
                if type(child_node) is bpy_prop_collection:
                    
                    bl_rna = getattr(child_node, 'bl_rna', '')
                    
                    item_of = getattr(bl_rna, 'identifier', '')
                    
                    
                    ret.extend([(grand_child, item_of) for grand_child in child_node\
                            if grand_child is not None])
                    
                    # for sub_child in child_node:
#                                                                             
#                         if not sub_child is None:
                        
                            
                            
                            # sub_chld_ptr = sub_child.as_pointer()
#                         
#                             if sub_chld_ptr in nodes:
#                             
#                                 
#                                 insert_child_node(
#                                     node = nodes[sub_chld_ptr], 
#                                     append=True,
#                                     item_of = getattr(bl_rna, 'identifier', ''))
#                                     
#                                 continue    
#                             
#                             else:
#                                 # print("adding a child node from sub_child", sub_child)
#                                 insert_child_node(data = sub_child, 
#                                     item_of = getattr(bl_rna, 'identifier', ''))
                
                elif type(child_node) in _dict[_type]\
                                        [child_data][attr_name]:
                    
                    
                    ret.append((child_node, None))
                    
                    # child_node_ptr = child_node.as_pointer()
#                     
#                     if child_node_ptr in hash_tree.nodes:
#                         
#                         # if bpy.app.debug:
# #                             print('adding an existing node as child \\n',
# #                                         'found :', hash_tree.nodes[child_node_ptr])
#                         
#                         insert_child_node(node = hash_tree.nodes[child_node_ptr], 
#                                                                 append=True)
#                         continue
                    
                    
                    
                   #  else: 
#                         
#                         
#                        #  if bpy.app.debug:
# #                             print("adding a child node")
# 
#                         insert_child_node(data = child_node)  
                                
                        
        else:
            ret = []
            # if bpy.app.debug:
#                 print('could not find any children here :', _type)

        return ret
        
    def iterate(self, data):
        """ return an iterable data object based on the input
        
        Methodology:
        
        Not all objects have the __iter__ attribute meaning they can't
        be used directly in a for loop. This leads to potential code bloating
        and so this method returns a dict item containing all the objects
        contained in data. Since py dictionaries are iterable it allows 
        a simple loop to be done. 
        
        arguments: data (type unknown till runtime), 
                   
        return value: list: iterable_data - list containing references
            to the data's attributes.
        side effects: 
        exceptions raised: none
        restrictions: Unknown
        
        """
        iterable_data = list()
        for name in dir(data):
            if name not in self.black_list:
                iterable_data.append( eval('data.' + name) )
                # print('START::', iterable_data, ' ::FINISH')
            
        return iterable_data                  
               
      
    def get_name(self, data):
        """ returns a string of the data objects name attribute
        
        Methodology:
        
        Hmmm this is really quite simple, each object in blender has a name,
        or it has bl_rna (or sometimes neither which is annoying) attribute
        that has a name. We simply return this name as a string. booya. 
        
        arguments: data (type unknown till runtime)
        return value: str: the contents of the 'name' attribute
        side effects: None known of
        exceptions raised: None, why would we raise an exception on purpose?
            Thats just dumb.....you avoid exceptions, you don't raise them.
        restrictions: Unknown
        
        """
        if hasattr(data, 'name'):
            return data.name
        elif hasattr(data, 'bl_rna'):
            return data.bl_rna.name
        else:
            return ''
    
    #@utils.func_time
    def hash(self, data):
        """ return the hash value of an object
        
        Methodology:
        
        This method uses a dictionary (_hash_functions)
        of small hash functions which operate
        on the different types of object used in blender. The algorithm 
        compares the type(data) with the keys of this dictionary and returns
        the matching function which is then used to hash the data. This 
        allows us to write many different hash functions that can be selected
        from very quickly without complex and lengthy if, elif statements. 
        
        """
        
        # Compare the type of the data input to the keys of the hash 
        # function dictionary. If there is a match then return the 
        # associated hash function and use this to has the data. 
        # Otherwise, just return zero, since we don't know what this data
        # is or how it should be hashed. Tip, loop up the documentation on the
        # hash() builtin function, if the data is a built in type like
        # int, str, bool, etc then hash will generate a hash value that is
        # unique for that value. However, if the data is an object with 
        # attributes that is not a builtin, the hash function returns 
        # a value that is a function of the data's location in memory. 
        # This makes it unsuitable for comparison across platforms since
        # the memory location will be different on different machines. 
        
        return self._hash_functions.get(type(data), 0)(data)
            
    def op_handler_map(self):
        
        """ returns a dict where keys - bl_idname, value - handler function
        """
        
        op_handlers = {'OBJECT_OT_editmode_toggle':self._obj_editmode_toggle,
                       'OBJECT_OT_delete':self._obj_delete,
                       'MESH_OT_primitive_cube_add':self._prim_mesh_add,
                       'MESH_OT_primitive_plane_add':self._prim_mesh_add,
                       'MESH_OT_primitive_cylinder_add':self._prim_mesh_add,
                       'MESH_OT_primitive_uv_sphere_add':self._prim_mesh_add,
                       'MESH_OT_primitive_ico_sphere_add':self._prim_mesh_add,
                       'MESH_OT_primitive_cone_add':self._prim_mesh_add,
                       'MESH_OT_primitive_torus_add':self._prim_mesh_add,
                       'MESH_OT_primitive_grid_add':self._prim_mesh_add,
                       'MESH_OT_primitive_monkey_add':self._prim_mesh_add,
                       'MESH_OT_landscape_add':self._prim_mesh_add,
                       'OBJECT_OT_duplicate_move':self._obj_duplicate,
                       'OBJECT_OT_material_slot_remove':self._obj_matslots_remove,
                       'OBJECT_OT_material_slot_add':self._obj_matslots_add,
                       'OBJECT_OT_duplicate':self._obj_duplicate,
                       'MATERIAL_OT_new':self._material_add_new,
                       'OBJECT_OT_material_slot_assign':self._material_assign,
                       'SCENE_OT_render_layer_add':self._render_layer_add,
                       'TRANSFORM_OT_translate':self._transform,
                       'TRANSFORM_OT_resize':self._transform,
                       'TRANSFORM_OT_rotate':self._transform,
                       'VIEW3D_OT_select_circle':self._selection_change,
                       'VIEW3D_OT_select_border':self._selection_change,
                       'SCENE_OT_new':self._scene_new
                       }
        
        return op_handlers
        
    def op_blidname_operator(self):
        """ returns a dictionary k = bl_idname, v = operator
        """               
        
        operators = {'OBJECT_OT_editmode_toggle':bpy.ops.object.editmode_toggle,
               'OBJECT_OT_delete':bpy.ops.object.delete,
               'MESH_OT_primitive_cube_add':bpy.ops.mesh.primitive_cube_add,
               'MESH_OT_primitive_plane_add':bpy.ops.mesh.primitive_plane_add,
               'MESH_OT_primitive_cylinder_add':bpy.ops.mesh.primitive_cylinder_add,
               'MESH_OT_primitive_uv_sphere_add':bpy.ops.mesh.primitive_uv_sphere_add,
               'MESH_OT_primitive_ico_sphere_add':bpy.ops.mesh.primitive_ico_sphere_add,
               'MESH_OT_primitive_cone_add':bpy.ops.mesh.primitive_cone_add,
               'MESH_OT_primitive_torus_add':bpy.ops.mesh.primitive_torus_add,
               'MESH_OT_primitive_grid_add':bpy.ops.mesh.primitive_grid_add,
               'MESH_OT_primitive_monkey_add':bpy.ops.mesh.primitive_monkey_add,
               'MESH_OT_landscape_add':bpy.ops.mesh.landscape_add,
               'OBJECT_OT_duplicate_move':bpy.ops.object.duplicate,
               'OBJECT_OT_duplicate':bpy.ops.object.duplicate,
               'OBJECT_OT_material_slot_add':bpy.ops.object.material_slot_add,
               'OBJECT_OT_material_slot_remove':bpy.ops.object.material_slot_remove,
               'MATERIAL_OT_new':bpy.ops.material.new,
               'OBJECT_OT_material_slot_assign':bpy.ops.object.material_slot_assign,
               'ED_OT_undo':bpy.ops.ed.undo,
               'ED_OT_redo':bpy.ops.ed.redo,
               'SCENE_OT_render_layer_add':bpy.ops.scene.render_layer_add,
               'SCENE_OT_new':bpy.ops.scene.new
                       }
                       
        return operators
        
    def get_node_parent(self, client, data):
        """ Returns the parent node for the host app object in data or None if not found
        """
        
        collection_type = _dict_of_types.get(type(data), None)
        
        parent_node = client._hash_tree.nodes_by_type.get(collection_type, None)
                                                         
        return parent_node
                       
    def _scene_new(self, client, update_item, context):
        """ Handles adding a new scene
        
        """
        
        context.scene.crowd_render.local_node.name = 'local'
        context.scene.crowd_render.local_node.node_uuid = 'local'
        context.scene.crowd_render.local_node.node_state = utils.synced
        
        scene_add_types = update_item['operator'].properties['type']
        
        parent_node = client._hash_tree.tree_root
                                               
        new_node = parent_node.insert_child_node(
                                        data=context.scene
                                                    )
        
                                                    
        client._hash_tree.update_node(initialising=False, node_uuid=parent_node.uuid)
        
        sync_item = utils.MsgWrapper(command = utils.data_update,
                                        
                            attributes = {
                            utils.scene:context.scene.name,
                            utils.scene_add_type:scene_add_types,
                            utils.top_hash:client._hash_tree.top_hash,
                            utils.operator:update_item['operator'].bl_idname
                                        }
                                        )
                                        
        
                                 
        return sync_item
        
        
        
                       
    def _obj_delete(self, client, update_item, context):
    
        nodes_to_delete = {}
        
        #If a delete operator is detected we need to delete the relevant node
        # and it's reference in client.selected    
            
        for obj_ptr in client.selected[previously_selected][dictionary].keys():
            node = client._hash_tree.nodes.get(obj_ptr)
            
            # no point going any further if this thing aint what we want
            if node is None: continue
            
            node_uuid = node.uuid
            nodes_to_delete[obj_ptr] = node_uuid
        
        node_ptrs = nodes_to_delete.keys()
        
        if client._hash_tree.delete_node(node_pointer = node_ptrs) > 0:
            client.logger.info("Nodes Succesfully Deleted")
        
        client.selected.clear()
        
        # tree_root_uuid = client._hash_tree.tree_root.uuid
#             
#         client._hash_tree.update_node(initialising=False, node_uuid=tree_root_uuid)
        
        if any(nodes_to_delete):
        
            sync_item = utils.MsgWrapper(command = utils.data_update,
                                attributes = {
                                utils.scene:context.scene.name,
                                utils.previously_selected:nodes_to_delete,
                                utils.top_hash:client._hash_tree.top_hash,
                                utils.operator:update_item['operator'].bl_idname
                                            }
                                            )

        else:
            #error condition
            print('WARNING!!!: No Nodes were found to DELETE!!!')
            sync_item = None
            
        
        return sync_item
            
        
        
    def _obj_duplicate(self, client, update_item, context):
    
        """ Handles the event of duplicating an object
        """
            
        
        selected_objs = context.selected_objects
        
        new_nodes = {}
        
        for obj in selected_objs:
        
            parent_node = self.get_node_parent(client, obj)
            
            if parent_node is not None:
                                               
                new_node = parent_node.insert_child_node(
                                            data=obj
                                                        )
                                                
                new_nodes[new_node.uuid] = {'location':obj.location,
                                             'rotation':obj.rotation_euler,
                                             'scale':obj.scale
                                            }
                                            
            else:
                raise RunTimeError("Could not find parent for :" + str(obj) +\
                    " during attempt to process duplicate operator")
                    
        #if a duplicate operation fails to produce any new ht nodes then there
        # is no point updating other compute nodes.                                         
        if new_nodes:

            client._hash_tree.update_node(initialising=False, node_uuid=parent_node.uuid)
        
            selected_uuids = [
                node.uuid for key,node in client._hash_tree.nodes.items()\
                if key in client.selected[previously_selected][dictionary].keys()
                            ]
        
            sync_item = utils.MsgWrapper(
                    
                        command = utils.data_update,
                        #TODO:JIRA:CR-46 Possibly need a review of the object's attributes
                        # here, for example, what if the transform properties were
                        # applied to the mesh? Any reason we think we're good just 
                        # using a handful of the attributes available to us?
                    
                        attributes = {
                            utils.scene:context.scene.name,
                            utils.previously_selected:selected_uuids,
                            utils.duplicated_nodes: new_nodes,
                            utils.parent_node_uuid:parent_node.uuid,
                            utils.top_hash:client._hash_tree.top_hash,
                            utils.operator:update_item['operator'].bl_idname
                                     }
                                        )
        else:
            sync_item = None
        
        return sync_item
        
        
    def _prim_mesh_add(self, client, update_item, context):
        """ Handles the event of adding a mesh to a scene
        
        """
                
        # The duplicated object will have the same parent as its
        # source object
        
        # First find out what the type of this object is so we can track
        # down its parent
        
        if type(update_item['data_object']) \
                            in _dict_of_types:
            #Find out which collection its in and then
            # add it as a new node in that collection.

            #ISSUE - Update_item[data_object]
            # will always be the active object.
            # because of this we can't currently detect
            # a new scene or new world or any top level
            # data blocks. We'd need to check these first
            # to see if there has been a new datablock 
            # added and then move onto the active object if
            # we can't find any new worlds, or scenes.
                        
            collection_type = _dict_of_types[
                            type(update_item['data_object'])
                                                ]
            
            parent_node = client._hash_tree.nodes_by_type[
                                        collection_type
                                                    ]
            # new_node = parent_node.insert_child_node(
                            # data=update_item['data_object']
                                                    # )

            # client._hash_tree.tree_root.aggregate_hash_values()

            # client._hash_tree.update_hashtree()
            client._hash_tree.update_node(initialising=False, node_uuid=parent_node.uuid)
            
            new_node = client._hash_tree.nodes[update_item['data_object'].as_pointer()]
            
            sync_item = utils.MsgWrapper(command = utils.data_update,
                                        
                            attributes = {
                            utils.scene:context.scene.name,
                            utils.node_uuid:new_node.uuid,
                            utils.parent_node_uuid:parent_node.uuid,
                            utils.top_hash:client._hash_tree.top_hash,
                            'location':update_item['data_object'].location,
                            'rotation_euler':update_item['data_object'].rotation_euler,
                            'scale':update_item['data_object'].scale,
                            utils.operator:update_item['operator'].bl_idname
                                        }
                                        )
                                 
            return sync_item
        
        
    
    def _obj_editmode_toggle(self, client, update_item, context):
        
        """ Handles the event of the user toggling edit mode
        """
        
        if not self.last_mode == bpy.context.mode:
        
            #mode change
            if context.mode == 'OBJECT':
                # need a method to re parse the mesh/curve/surface etc 
                # This requires removing the mesh/curve/surface
                # from all dictionaries.
                # remove the mesh then.
                
                #TODO:JIRA:CR-45 ugly hardcoding of a key for the update_item collection, 
                # the keys are defined in client.py, might be better off having this in
                # utils.
                context.scene.crowd_render.data_is_updated = True
                #client._hash_tree.nodes[update_item['pointer']].children[0].delete()
                
                # Changed this method to now re-initialise the active_object rather than
                # merely search its data structure.
                #client._hash_tree.update_node(True, update_item['pointer'])
                
                
                
                context.scene.crowd_render.data_is_updated = False
                
                #TODO:JIRA:CR-47 Generally I don't think its a good idea to have a 
                # critical component of the hash calculation done in many areas
                # it would be better to have the following two lines of code (which
                # aggregate the hashes in the tree and then update the top hash) 
                # in only one location, preferably at the end of the block of code
                # in client that deals with each scene update.
                
                
            
            elif context.mode == 'EDIT':
                
                context.scene.crowd_render.data_is_updated = False
                 
        
        self.last_mode = context.mode        
                           
        
        client.logger.info("CRRules._obj_editmode_toggle: " +\
             l_sep + "mode is now " + context.mode)
        
        
    def _obj_matslots_add(self, client, update_item, context):
        """ Re process the material slots when one is added or removed.
    
    
        """
        material_slots = list()
            
        #Find the node that just changed.
        update = client._hash_tree.update_node(True, node_pointer = update_item['pointer'])

        
        sync_item = utils.MsgWrapper(command = utils.data_update,
                    #TODO:JIRA:CR-46 Possibly need a review of the object's attributes
                    # here, for example, what if the transform properties were
                    # applied to the mesh? Any reason we think we're good just 
                    # using a handful of the attributes available to us?
                    
                    attributes = {
                    utils.scene:context.scene.name,
                    #utils.second_last_uuid:update_item[utils.second_last_uuid],
                    utils.node_uuid:update_item['item_uuid'],
                    #utils.parent_node_uuid:parent_node.uuid,
                    utils.top_hash:client._hash_tree.top_hash,
                    #'location':update_item['data_object'].location,
                    #'rotation_euler':update_item['data_object'].rotation_euler,
                    #'scale':update_item['data_object'].scale,
                    utils.operator:update_item['operator'].bl_idname,
                    utils.active_mat_ind:update_item['data_object'].active_material_index
                                }
                                )
        
        return sync_item
                       
    def _obj_matslots_remove(self, client, update_item, context):
        """ Re process the material slots when one is added or removed.
    
    
        """
        
            
        #Find the node representing the material slot.
        
        #TODO, find some way of doing this without having to reprocess all
        # data blocks in the active node.
        active_node = client._hash_tree.update_node(True, node_pointer = update_item['pointer'])
        
        
        sync_item = utils.MsgWrapper(command = utils.data_update,
                    #TODO:JIRA:CR-46 Possibly need a review of the object's attributes
                    # here, for example, what if the transform properties were
                    # applied to the mesh? Any reason we think we're good just 
                    # using a handful of the attributes available to us?
                    
                    attributes = {
                    utils.scene:context.scene.name,
                    #utils.second_last_uuid:update_item[utils.second_last_uuid],
                    utils.node_uuid:update_item['item_uuid'],
                    #utils.parent_node_uuid:parent_node.uuid,
                    utils.top_hash:client._hash_tree.top_hash,
                    #'location':update_item['data_object'].location,
                    #'rotation_euler':update_item['data_object'].rotation_euler,
                    #'scale':update_item['data_object'].scale,
                    utils.operator:update_item['operator'].bl_idname,
                    utils.active_mat_ind:update_item['data_object'].active_material_index
                                }
                                )
        
        return sync_item
        
    def _material_add_new(self, client, update_item, context):
        """ Re process the material slots when one is added or removed.
    
    
        """
        material_slots = list()
            
        #Find the node that just changed.
        active_node = client._hash_tree.update_node(True, node_pointer = update_item['pointer'])
                
        active_mat_ind = update_item['data_object'].active_material_index
        
        active_mat_slot = update_item['data_object'].material_slots[active_mat_ind]
        
        new_material = update_item['data_object'].active_material
        
        use_nodes = new_material.use_nodes
        
        sync_item = utils.MsgWrapper(command = utils.data_update,
                    #TODO:JIRA:CR-46 Possibly need a review of the object's attributes
                    # here, for example, what if the transform properties were
                    # applied to the mesh? Any reason we think we're good just 
                    # using a handful of the attributes available to us?
                    
                    attributes = {
                    utils.scene:context.scene.name,
                    #utils.second_last_uuid:update_item[utils.second_last_uuid],
                    utils.node_uuid:update_item['item_uuid'],
                    utils.use_nodes:use_nodes,
                    utils.active_mat_slot:active_mat_slot.name,
                    #utils.parent_node_uuid:parent_node.uuid,
                    utils.top_hash:client._hash_tree.top_hash,
                    #'location':update_item['data_object'].location,
                    #'rotation_euler':update_item['data_object'].rotation_euler,
                    #'scale':update_item['data_object'].scale,
                    utils.operator:update_item['operator'].bl_idname,
                    utils.active_mat_ind:active_mat_ind
                                }
                                )
        #TODO as part of issue CR24 we need to change the message structure to have 
        # the parent node included and also the fact that its name changes to the name of
        # the new material. Look to the duplicate method for inspiration since this 
        # uses the parent node of the duplicate.
        
        return sync_item
    
    def _material_assign(self, client, update_item, context):
    
        update = client._hash_tree.update_node(True, update_item['pointer'])
                
        active_mat_ind = update_item['data_object'].active_material_index
        
        active_mat_slot = update_item['data_object'].material_slots[active_mat_ind]
                    
        sync_item = utils.MsgWrapper(command = utils.data_update,
                    #TODO:JIRA:CR-46 Possibly need a review of the object's attributes
                    # here, for example, what if the transform properties were
                    # applied to the mesh? Any reason we think we're good just 
                    # using a handful of the attributes available to us?
                    
                    attributes = {
                    utils.scene:context.scene.name,
                    #utils.second_last_uuid:update_item[utils.second_last_uuid],
                    utils.node_uuid:update_item['item_uuid'],
                    utils.active_mat_slot:active_mat_slot.name,
                    #utils.parent_node_uuid:parent_node.uuid,
                    utils.top_hash:client._hash_tree.top_hash,
                    #'location':update_item['data_object'].location,
                    #'rotation_euler':update_item['data_object'].rotation_euler,
                    #'scale':update_item['data_object'].scale,
                    utils.operator:update_item['operator'].bl_idname,
                    utils.active_mat_ind:active_mat_ind
                                }
                                )
                                
        #TODO:JIRA: CR-74 There needs to be a call to 
        #client.msg_queue.put(sync_item) 
        # here like other handlers but this currently might break things since although
        # we can detect the handler, we then have to also discover which vertices were
        # affected which involves running client.process_nodes. However we then 
        # need to be careful about what this does since any changes will trigger 
        # a sync item being placed into the client.msg_queue and sending the update
        # prior to this code being able to do the same (depends on the sequence of
        # calls to the client.msg_queue.put() and client.process_nodes() methods).
        # At the very least a code review is required to get this right, the code 
        # at the beginning of this method looks redundant (prob copy paste from another
        # method?) and therefore not relevant to solving the problem here. 
        
        
                                        
    def _undo(self, client, update_item):
        
        sync_item = utils.MsgWrapper(command = utils.data_update,
                            attributes = { 
                            utils.scene:bpy.context.scene.name,
                            utils.top_hash:client._hash_tree.top_hash,
                            utils.operator:update_item['operator']
                                }
                            )
                                    
        
        return sync_item
        
    def _redo(self, client, update_item):
        
        sync_item = utils.MsgWrapper(command = utils.data_update,
                            attributes = {
                            utils.scene:bpy.context.scene.name, 
                            utils.top_hash:client._hash_tree.top_hash,
                            utils.operator:update_item['operator']
                                }
                            )
                                    
                                    
        return sync_item                           
        
    def _render_layer_add(self, client, update_item, context):
        #
        active_layer_name = bpy.context.scene.render.layers.active.name
        active_scene_name = bpy.context.scene.name
        
        #Update the hash tree so that the server doesn't freak out
        #after adding the render_layer because the client gave it 
        #the old hash value.
        client._hash_tree.update_node(False, '_BlendData::' +\
                                active_scene_name +\
                                '_Scene::_RenderSettings')
        
        
        sync_item =  utils.MsgWrapper(command = utils.data_update,                                        
                            attributes = {
                            utils.scene:context.scene.name,
                            utils.top_hash:client._hash_tree.top_hash,
                            utils.operator:update_item['operator'].bl_idname,
                            utils.render_layer_name:active_layer_name                            
                                        }
                                        )                                    
                                    
        return sync_item
        
    def _transform(self, client, update_item, context):
    
        update_items = {}
        
        for ptr_val, obj in client.selected[last][dictionary].items():
            tform_vector = {}
            #We need to make sure all selected objects data is forwarded to the
            # server nodes            
            data_object_node = client._hash_tree.nodes.get(ptr_val)
            #if the object is null just skip it, protects against traceback errors
            
            parent_node = client._hash_tree.rules.get_node_parent(client, obj)
            
            if data_object_node is None and parent_node is not None: 
            
                
                
                data_object_node = parent_node.insert_child_node(
                                            data=obj
                                                        )
                
                
            
            elif data_object_node is None and parent_node is None:
                
                raise RuntimeError("could not find the parent node for : " +\
                    str(obj) + " during transform operator")
                
                       
            tform_vector[utils.location] = data_object_node.data.location
            tform_vector[utils.scale] = data_object_node.data.scale
            tform_vector[utils.rotation] = data_object_node.data.rotation_euler
            
            update_items[data_object_node.uuid] = tform_vector
            
            client._hash_tree.update_node(initialising =\
                False, node_uuid = data_object_node.uuid)

        sync_item = utils.MsgWrapper(command = utils.data_update, 
                            attributes = {
                            utils.scene:context.scene.name,
                            utils.transform_vector:update_items,
                            utils.top_hash:client._hash_tree.top_hash,
                            utils.operator:update_item['operator'].bl_idname
                                }
                            )
        
        return sync_item
    
    def _selection_change(self, client, context):
    
        print('Selection Change detected')
                           
        if len(client.selected)>0:    
            if context.selected_objects != client.selected[last][utils.list_selected]: 
                client.selected.append(context.selected_objects)
        
        else:
            client.selected.append(context.selected_objects)