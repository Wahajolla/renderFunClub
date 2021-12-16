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

import bpy
# from . import rules

animation_data_attribs = {
                            'action_blend_type',
                            'action_extrapolation',
                            'action_influence',
                            'use_nla',
                            'use_tweak_mode'
}

mist_settings_attribs = {
                            'depth'
                            'falloff'
                            'height'
                            'intensity'
                            'start'
                            'use_mist'
                            }

light_settings_attribs = {'adapt_to_speed'
                            'ao_blend_type'
                            'ao_factor'
                            'bias'
                            'correction'
                            'distance'
                            'environment_color'
                            'environment_energy'
                            'error_threshold'
                            'falloff_strength'
                            'gather_method'
                            'indirect_bounces'
                            'indirect_factor'
                            'passes'
                            'sample_method'
                            'samples'
                            'threshold'
                            'use_ambient_occlusion'
                            'use_cache'
                            'use_environment_light'
                            'use_falloff'
                            'use_indirect_light'
                            }
                            
material_data_block_attribs = {'active_texture_index', 'alpha',
                                'ambient', 'darkness', 'diffuse_color',
                                'diffuse_fresnel', 'diffuse_fresnel_factor',
                                'diffuse_intensity', 'diffuse_ramp_blend',
                                'diffuse_ramp_factor', 'diffuse_ramp_input',
                                'diffuse_shader', 'diffuse_toon_size',
                                'diffuse_toon_smooth', 'emit',
                                'invert_z', 'line_color', 'line_priority',
                                'mirror_color', 'mirror_color',
                                'paint_active_slot', 'paint_clone_slot',
                                'pass_index', 'preview_render_type',
                                'roughness', 'shadow_buffer_bias',
                                'shadow_cast_alpha', 'shadow_only_type',
                                'shadow_ray_bias', 'specular_alpha',
                                'specular_color', 'specular_hardness',
                                'specular_intensity', 'specular_ior',
                                'specular_ramp_blend', 'specular_ramp_factor', 
                                'specular_ramp_input', 'specular_shader',
                                'specular_slope', 'specular_toon_size',
                                'specular_toon_smooth', 'translucency',
                                'transparency_method', 'type',
                                'use_cast_approximate', 'use_cast_buffer_shadows',
                                'use_cast_shadows', 'use_cast_shadows_only',
                                'use_cubic', 'use_diffuse_ramp',
                                'use_face_texture', 'use_face_texture_alpha',
                                'use_full_oversampling', 'use_light_group_exclusive',
                                'use_light_group_local', 'use_mist', 
                                'use_nodes', 'use_object_color', 
                                'use_only_shadow', 'use_ray_shadow_bias',
                                'use_raytrace', 'use_shadeless',
                                'use_shadows', 'use_sky', 'use_specular_ramp', 
                                'use_tangent_shading','use_textures', 
                                'use_transparency', 'use_transparent_shadows',
                                'use_uv_project', 'use_vertex_color_light',
                                'use_vertex_color_paint', }

obj_data_block_attribs = {'dupli_type', 'field', 'animation_data_clear', 
                              'particle_systems', 'layers_local_view', 
                              'ray_cast', 'use_dupli_faces_scale', 
                              'dupli_frames_end', 'layers', 
                              'empty_draw_type', 
                              'use_dynamic_topology_sculpting', 
                              'track_axis', 'proxy', 'parent_vertices', 
                              'rna_type', 'dupli_list_create', 'soft_body', 
                              'rotation_euler', 'update_from_editmode', 
                              'cycles_visibility', 'empty_draw_size', 
                              'show_only_shape_key', 'use_fake_user', 
                              'show_transparent', 'pass_index', 
                              'material_slots', 'copy', 
                              'find_armature', 'matrix_world', 
                              'dupli_list_clear', 'pose_library', 
                              'delta_location', 'active_shape_key', 
                              'show_wire', 'active_material', 
                              'animation_data', 'use_extra_recalc_data', 
                              'use_dupli_vertices_rotation', 
                              'empty_image_offset', 'to_mesh', 'show_name', 
                              'dupli_frames_off', 'is_library_indirect', 
                              'select', 'dimensions',
                              'active_shape_key_index', '__doc__', 
                              'grease_pencil', 'use_dupli_frames_speed', 
                              '__module__', 'lock_rotations_4d', 
                              'up_axis', 'animation_data_create', 
                              'delta_scale', 'users', 'active_material_index', 
                              'delta_rotation_quaternion', 
                              'delta_rotation_euler', 'game', #'tag', 
                              'collision', 'rotation_quaternion', 
                              'is_deform_modified', 'rigid_body_constraint', 
                              'pose', 'constraints', 'hide_render', 
                              'lock_location', 'type', 'convert_space', #'update_tag', 
                              'motion_path', 
                              'dupli_frames_on', '__qualname__', 
                              'use_extra_recalc_object', 'data', 
                              'show_all_edges', 'lock_rotation', 
                              'show_axis', 'draw_bounds_type', 
                              'use_shape_key_edit_mode', 'is_updated_data', 
                              'library', 'is_modified', 'shape_key_add', 
                              'closest_point_on_mesh', 
                              'animation_visualization', 'location', 
                              'dm_info', 'dupli_list', 'show_x_ray', 
                              'lock_rotation_w', 'user_clear', 
                              'dupli_faces_scale', 'is_updated', 
                              'use_slow_parent', 'slow_parent_offset', 
                              'scale', 'is_visible', 'matrix_basis', 
                              '__slots__', 'parent_type', 'parent_bone', 
                              'vertex_groups', 'modifiers', 'matrix_local', 
                              'show_texture_space',
                              'dupli_frames_start', 'parent', 'show_bounds', 
                              'lock_scale', 'rotation_mode', #'bound_box', 
                              'draw_type', 'hide', #'name', 
                              'hide_select', 
                              'rotation_axis_angle', 'rigid_body', 'color', 
                              'dupli_group', 'is_duplicator', 
                              'matrix_parent_inverse', 'bl_rna', 
                              'proxy_group' }# 'mode'} # mode refers to whether
                              # the object is being edited or not. Not required
                              # for hashing.
    
mesh_data_block_attribs =  {'uv_layer_clone', 'animation_data_clear', 
                                'use_paint_mask_vertex', 'total_edge_sel', 
                                'show_edge_seams', 'transform', 'cycles', 
                                'uv_layer_clone_index', 'total_face_sel', 
                                'validate', 'use_customdata_edge_bevel', 
                                'show_normal_vertex', 'loops', 'rna_type', 
                                'from_pydata', 'show_faces', 
                                'unit_test_compare', 'update', 
                                'use_auto_texspace', 'use_fake_user', 
                                'tessface_vertex_colors',  
                                'copy', 'use_customdata_vertex_bevel', 
                                'show_extra_face_area', 'skin_vertices', 
                                'show_normal_face', 'uv_texture_stencil', 
                                'total_vert_sel', 'show_statvis', 
                                'animation_data', 'uv_layer_stencil_index', 
                                'use_auto_smooth', 'show_weight', 
                                'use_paint_mask', 'is_library_indirect', 
                                'auto_smooth_angle', 'vertex_colors', 
                                'texspace_location', 'texco_mesh', 
                                'is_editmode', 'polygons', 
                                'uv_layer_stencil', 
                                'show_freestyle_face_marks', 
                                'calc_normals_split', '__module__', 
                                'show_double_sided', 
                                'animation_data_create', 'users', 
                                'show_extra_edge_length', 'calc_tessface', 
                                'tessfaces', #'tag', 
                                'uv_layers', 
                                'show_freestyle_edge_marks', 
                                'uv_textures', 'free_normals_split', 
                                'materials', #'update_tag', 
                                'calc_smooth_groups', '__qualname__', 
                                'show_edge_sharp', 'is_updated_data', 
                                'show_extra_face_angle', 'library', 
                                '__doc__', 'texture_mesh', 
                                'texspace_size', 'uv_texture_stencil_index', 
                                'use_mirror_x', 'use_mirror_topology', 
                                'uv_texture_clone_index', 'user_clear', 
                                'auto_texspace', 'show_edges', 'is_updated', 
                                'edges', 'show_edge_bevel_weight', 
                                'bl_rna', '__slots__', 'show_extra_indices', 
                                'show_edge_crease', 
                                'polygon_layers_float', 
                                'polygon_layers_int', 
                                'show_extra_edge_angle', 
                                'tessface_uv_textures', #'name', 
                                'uv_texture_clone', 'shape_keys', 
                                'use_customdata_edge_crease', 
                                'calc_normals', 
                                'polygon_layers_string', 'vertices'}
                                
camera_data_block_attribs = {#'angle', #'angle_x', 'angle_y',
                            'clip_end', 'clip_start',
                            'dof_distance', 'draw_size',
                            'lens', 'lens_unit',
                            'ortho_scale', 'passepartout_alpha',
                            'sensor_fit', 'sensor_height',
                            'sensor_width', 'shift_x',
                            'shift_y', 'show_guide', 
                            'show_limits', 'show_mist',
                            'show_name', 'show_passepartout',
                            'show_safe_areas', 'show_safe_center',
                            'show_sensor', 'type'}

lamp_data_attribs = {'active_texture', 'active_texture_index', 'color',
                    'distance', 'energy', 'type',  
                    'use_diffuse', 'use_negative', 'use_nodes',
                    'use_own_layer', 'use_specular'}

area_lamp_data_attribs = {  'compression_threshold', 'gamma', 
                        'ge_shadow_buffer_type', 'shadow_adaptive_threshold', 
                        'shadow_buffer_bias', 'shadow_buffer_bleed_bias', 
                        'shadow_buffer_clip_end', 'shadow_buffer_clip_start', 
                        'shadow_buffer_samples', 'shadow_buffer_size', 
                        'shadow_buffer_soft', 'shadow_buffer_type', 
                        'shadow_color', 'shadow_filter_type', 'shadow_method', 
                        'shadow_ray_sample_method', 'shadow_ray_samples_x', 
                        'shadow_ray_samples_y', 'shadow_sample_buffers', 
                        'shadow_soft_size', 'shape', 'size', 'size_y', 
                        'use_auto_clip_end', 'use_auto_clip_start', 
                        'use_dither', 'use_jitter', 'use_only_shadow', 
                        'use_shadow', 'use_shadow_layer', 'use_umbra'}

point_lamp_data_attribs = { 'compression_threshold', 'constant_coefficient',
                            'falloff_type', 'ge_shadow_buffer_type', 
                            'linear_attenuation', 'linear_coefficient', 
                            'quadratic_attenuation', 'quadratic_coefficient', 
                            'shadow_adaptive_threshold', 'shadow_buffer_bias', 
                            'shadow_buffer_bleed_bias', 'shadow_buffer_clip_end', 
                            'shadow_buffer_clip_start', 'shadow_buffer_samples', 
                            'shadow_buffer_size', 'shadow_buffer_soft', 
                            'shadow_buffer_type', 'shadow_color', 
                            'shadow_filter_type', 'shadow_method', 
                            'shadow_ray_sample_method', 'shadow_ray_samples', 
                            'shadow_sample_buffers', 'shadow_soft_size', 
                            'use_auto_clip_end', 'use_auto_clip_start', 
                            'use_only_shadow', 'use_shadow', 'use_shadow_layer', 
                            'use_sphere'}

spot_lamp_data_attribs = {'compression_threshold', 'constant_coefficient', 
                        'falloff_type', 'ge_shadow_buffer_type', 
                        'halo_intensity', 'halo_step', 'linear_attenuation', 
                        'linear_coefficient', 'quadratic_attenuation', 
                        'quadratic_coefficient', 'shadow_adaptive_threshold', 
                        'shadow_buffer_bias', 'shadow_buffer_bleed_bias', 
                        'shadow_buffer_clip_end', 'shadow_buffer_clip_start', 
                        'shadow_buffer_samples', 'shadow_buffer_size', 
                        'shadow_buffer_soft', 'shadow_buffer_type', 
                        'shadow_color', 'shadow_filter_type', 'shadow_method', 
                        'shadow_ray_sample_method', 'shadow_ray_samples', 
                        'shadow_sample_buffers', 'shadow_soft_size', 'show_cone', 
                        'spot_blend', 'spot_size', 'use_auto_clip_end', 
                        'use_auto_clip_start', 'use_halo', 'use_only_shadow', 
                        'use_shadow', 'use_shadow_layer', 'use_sphere', 
                        'use_square'}

sun_lamp_data_attribs = {'compression_threshold', 'ge_shadow_buffer_type', 
                        'shadow_adaptive_threshold', 'shadow_buffer_bias', 
                        'shadow_buffer_bleed_bias', 'shadow_buffer_clip_end', 
                        'shadow_buffer_clip_start', 'shadow_buffer_samples', 
                        'shadow_buffer_size', 'shadow_buffer_soft', 
                        'shadow_buffer_type', 'shadow_color', 
                        'shadow_filter_type', 'shadow_frustum_size', 
                        'shadow_method', 'shadow_ray_sample_method', 
                        'shadow_ray_samples', 'shadow_sample_buffers', 
                        'shadow_soft_size', 'show_shadow_box', 
                        'use_auto_clip_end', 'use_auto_clip_start', 
                        'use_only_shadow', 'use_shadow', 'use_shadow_layer'}                        
                    
subsurf_mods_attribs = { '__doc__', '__module__', '__slots__', 'bl_rna', 
                         'levels', #'name', 
                         'render_levels', 'rna_type', 
                         'show_expanded', 'show_in_editmode', 'show_on_cage', 
                         'show_only_control_edges', 'show_render', 
                         'show_viewport', 'subdivision_type', 'type', 
                         'use_apply_on_spline', 'use_subsurf_uv'}
                         
                         
                         
node_attribs = {#'dimensions',#'inputs', 
                'internal_links', 'label','mute',
                #'name', #'outputs' , 'location',
                'parent', #'select', #'tile_order', 
                'type',
                'use_alpha' #'use_custom_color'
                }
                                                   
vertex_data_block_attribs = {'bevel_weight','co', 'index', 'normal', 'select',
                                'undeformed_co'}   
polygon_data_block_attribs = {'index', 'loop_indices', 'loop_start', 'loop_total',
                                'material_index', 'use_freestyle_mark', 'use_smooth'}
                                
scene_data_block_attribs = {' frame_current', ' frame_end',
                        'frame_preview_end', 'frame_preview_start', 'frame_start',
                        'frame_step', 'gravity', 'lock_frame_selection_to_range',
                        'show_keys_from_selected_only', 'sync_mode', 'use_audio',
                         'use_audio_scrub', 'use_audio_sync', 'use_frame_drop', 
                         'use_gravity', #'use_nodes', # temp disabled until we support
                        # distributed compositing properly
                        'use_preview_range', 'use_stamp_note', 'layers'
                           }             
                           
world_data_block_attribs = {'active_texture_index', 'ambient_color',
                            'color_range', 'exposure', 
                            'horizon_color', 'use_nodes',
                            'use_sky_blend', 'use_sky_paper',
                            'use_sky_real', 'zenith_color',
                            'node_tree', 'cycles', 'color'
                            }
                            
render_settings_attribs = {'alpha_mode', 'antialiasing_samples',
                        'bake_aa_mode', 'bake_bias', 'bake_distance'
                        'bake_margin', 'bake_normal_space',
                        'bake_quad_split', 'bake_samples',
                        'bake_type', 'bake_user_scale',
                        'dither_intensity', 'edge_color',
                        'edge_threshold', 'filter_size', 'field_order'
                        'line_thickness', 'line_thickness_mode',
                        'motion_blur_samples', 'motion_blur_shutter',
                        'motion_blur_shutter_curve', 'octree_resolution',
                        'pixel_aspect_x', 'pixel_aspect_y',
                        'pixel_filter_type', 'preview_start_resolution',
                        'raytrace_method', 'resolution_percentage',
                        'resolution_x', ' resolution_y',
                        'simplify_ao_sss', 'simplify_child_particles',
                        'simplify_child_particles_render',
                        'simplify_shadow_samples', 'simplify_subdivision',
                        'simplify_subdivision_render', 'stamp_background',
                        'stamp_font_size', 'stamp_foreground',
                        'stamp_note_text', 'stereo_views',
                        'threads', 'threads_mode',
                        'tile_x', 'tile_y',
                        'use_antialiasing', 'use_bake_antialiasing',
                        'use_bake_clear', 'use_bake_lores_mesh',
                        'use_bake_multires', 'use_bake_normalize',
                        'use_bake_selected_to_active', 'use_bake_to_vertex_color',
                        'use_bake_user_scale', #'use_border', 'use_compositing',
                        'use_edge_enhance', #'use_crop_to_border' 
                        'use_envmaps', 'use_fields', 'use_fields_still',
                        'use_free_image_textures', 'use_freestyle',
                        'use_full_sample', 'use_instances',
                        'use_local_coords', # use_lock_interface
                        'use_motion_blur', 'use_multiview',
                        'use_overwrite', 'use_persistent_data',
                        'use_placeholder', 'use_raytrace',
                        'use_render_cache', 'use_save_buffers', # use_sequencer
                        'use_shading_nodes', 'use_shadows',
                        'use_simplify', 'use_simplify_triangulate',
                        'use_single_layer', 'use_spherical_stereo',
                        'use_sss', 'use_stamp',
                        'use_stamp_camera', 'use_stamp_date', 'use_stamp_filename',
                        'use_stamp_frame', 'use_stamp_labels', 'use_stamp_lens',
                        'use_stamp_marker', 'use_stamp_memory', 'use_stamp_note',
                        'use_stamp_render_time', 'use_stamp_scene', 
                        'use_stamp_sequencer_strip', 'use_stamp_strip_meta',
                        'use_stamp_strip_meta', 'use_textures', 
                        'use_world_space_shading', 'views_format',
                         }
                         
render_layer_attributes = {
                        'exclude_ambient_occlusion',
                        'exclude_emit',
                        'exclude_environment',
                        'exclude_indirect',
                        'exclude_reflection',
                        'exclude_refraction',
                        'exclude_shadow',
                        'exclude_specular',
                        'invert_zmask',
                        'layers',
                        'layers_exclude',
                        'layers_zmask',
                        'light_override',
                        'material_override',
                        'name',
                        'pass_alpha_threshold',
                        'samples',
                        'use',
                        'use_all_z',
                        'use_ao',
                        'use_edge_enhance',
                        'use_freestyle',
                        'use_halo',
                        'use_pass_ambient_occlusion',
                        'use_pass_color',
                        'use_pass_combined',
                        'use_pass_diffuse',
                        'use_pass_diffuse_color',
                        'use_pass_diffuse_direct',
                        'use_pass_diffuse_indirect',
                        'use_pass_emit',
                        'use_pass_environment',
                        'use_pass_glossy_color',
                        'use_pass_glossy_direct',
                        'use_pass_glossy_indirect',
                        'use_pass_indirect',
                        'use_pass_material_index',
                        'use_pass_mist',
                        'use_pass_normal',
                        'use_pass_object_index',
                        'use_pass_reflection',
                        'use_pass_refraction',
                        'use_pass_shadow',
                        'use_pass_specular',
                        'use_pass_subsurface_color',
                        'use_pass_subsurface_direct',
                        'use_pass_subsurface_indirect',
                        'use_pass_transmission_color',
                        'use_pass_transmission_direct',
                        'use_pass_transmission_indirect',
                        'use_pass_uv',
                        'use_pass_vector',
                        'use_pass_z',
                        'use_sky',
                        'use_solid',
                        'use_strand',
                        'use_zmask',
                        'use_ztransp'
                        }
                         
node_tree_data_block_attributes = {
                        'active_input', 'active_output',
                        'type'}
                        
texture_data_block_attributes = {
                        'contrast', 'factor_blue',
                        'factor_green', 'factor_red',
                        'intensity', 'saturation', 'type',
                        'use_clamp', 'use_color_ramp',
                        'use_nodes', 'use_preview_alpha'
                        }
#all node sockets are the same for our hashing purposes.
node_socket ={'default_value', 'name',
                    'enabled', 'identifier',
                    'type'}
                    
shader_node_attributes = set(node_attribs)

shader_node_attribute_attributes = shader_node_attributes.union('attribute_name')
shader_node_bsdf_anisotropic_attributes =  shader_node_attributes.union('distribution')
shader_node_bsdfglass_attributes = shader_node_attributes.union('distribution')
shader_node_bsdfglossy_attributes = shader_node_attributes.union('distribution')
shader_node_bsdfhair_attributes = shader_node_attributes.union('component')
shader_node_bsdfprincipled_attributes = shader_node_attributes.union('distribution')
shader_node_bsdfrefraction_attributes = shader_node_attributes.union('distribution')
shader_node_bsdftoon_attributes = shader_node_attributes.union('component')
shader_nodebump_attributes = shader_node_attributes.union('invert')
shader_node_extendedmaterial_attributes = shader_node_attributes.union({'invert_normal', 
                                                                'use_diffuse',
                                                                'use_specular'})
shader_node_geometry_attributes = shader_node_attributes.union({'color_layer', 
                                                            'uv_layer'})
shader_node_mapping_attributes = shader_node_attributes.union({'max', 'min', 'rotation',
                                                        'scale', 'translation',
                                                        'use_max', 'use_min',
                                                        'vector_type'})
shader_node_material_attributes = shader_node_attributes.union({'invert_normal', 
                                                                'use_diffuse',
                                                                'use_specular'}) 
shader_node_math_attributes = shader_node_attributes.union({'operation','use_clamp'})   
shader_bnode_mixrgb_attributes = shader_node_attributes.union({'blend_type', 'use_alpha',
                                                            'use_clamp'})
shader_node_normal_map_attributes = shader_node_attributes.union({'space', 'uv_map'})
shader_node_output_attributes = shader_node_attributes.union({'is_active_output'})
shader_node_outputlamp_attributes = shader_node_attributes.union({'is_active_output'})
shader_node_output_linestyle_attributes = shader_node_attributes.union({'blend_type',
                                                                    'is_active_output',
                                                                    'use_alpha',
                                                                    'use_clamp'
                                                                    })
shader_node_output_material_attributes = shader_node_attributes.union('is_active_output')
shader_node_output_world_attributes = shader_node_attributes.union({'is_active_output'})
shader_node_particleinfo_attributes = shader_node_attributes.union({'is_active_output'})
shader_node_script_attributes = shader_node_attributes.union({'bytecode', 'bytecode_hash',
                                                        'filepath', 'mode',
                                                        'use_auto_update'})
shader_node_sss_attributes = shader_node_attributes.union({'falloff'})
shader_node_tangent_attributes = shader_node_attributes.union({'axis', 'direction_type',
                                                            'uv_map'})
shader_node_texbrick_attributes = shader_node_attributes.union({'offset', 
                                                            'offset_frequency',
                                                            'squash', 'squash_frequency',
                                                            'texture_mapping'})
shader_node_texcoord_attributes =  shader_node_attributes.union({'from_dupli'})
shader_node_texenvironment_attributes = shader_node_attributes.union({'color_space',
                                                                'interpolation',
                                                                'projection',
                                                                })
shader_node_texgradient_attributes = shader_node_attributes.union({'gradient_type'})
shader_node_teximage_attributes = shader_node_attributes.union({'color_space',
                                                            'extension',
                                                            'interpolation',
                                                            'projection',    
                                                            'projection_blend'})
shader_node_texmagic_attributes = shader_node_attributes.union({'turbulence_depth'})
shader_node_texmusgrave_attributes = shader_node_attributes.union({'musgrave_type'})
shader_node_texpointdensity_attributes = shader_node_attributes.union({'interpolation',
                                                            'particle_color_source',
                                                            'point_source',
                                                            'radius',
                                                            'resolution',
                                                            'space',
                                                            'vertex_attribute_name',
                                                            'vertex_color_source',
                                                            })
shader_node_texsky_attributes = shader_node_attributes.union({'ground_albedo', 'sky_type',
                                                            'sun_direction', 
                                                            'turbidity'})
shader_node_texvoronoi_attributes = shader_node_attributes.union({'coloring'})
shader_node_texwave_attributes = shader_node_attributes.union({'wave_profile', 
                                                                'wave_type'})
shader_node_texture_attributes = shader_node_attributes.union({'node_output'})
shader_node_tree_attributes = set()
shader_node_uvalongstroke_attributes = shader_node_attributes.union({'use_tips'})
shader_node_uvmap_attributes = shader_node_attributes.union({'from_dupli', 'uv_map'})
shader_node_vectormath_attributes = shader_node_attributes.union({'operation'})
shader_node_vectortransform_attributes = shader_node_attributes.union({'convert_from',
                                                                'convert_to',
                                                                'vector_type'})
shader_node_wireframe_attributes = shader_node_attributes.union({'use_pixel_size'})
  



                                                            
                                                            
                                                        

                                                            

#TODO:JIRA:CR-63 and most likely very important! This list has been added to lately with a view
# to 'getting this to work', as opposed to a robust analysis of what each item does and
# whether it affects the final render directly. Some of these are convenience variables
# others are properties of the UI such as cursor location (though arguably cursor_location
# is invaluable data to have when adding a new object as the new object will be
# located at the coordinates of the cursor). 

black_list = {'__bool__', '__contains__', '__delattr__', 
                           '__delitem__', '__doc__', '__doc__', 
                           '__getattribute__', '__getitem__', '__iter__', 
                           '__len__', '__module__', '__setattr__', 
                           '__setitem__', '__slots__', '__qualname__', 'int',
                           'rna_type', 'bl_rna', '__package__',
                           'keys', 'foreach_get', 'new', 
                           'find', 'is_updated', 'is_updated_data', 
                           'remove', 'data', 'as_pointer',
                           'items', 'get', 'foreach_get',
                           'animation_data_clear', 'animation_data_create',
                           'closest_point_on_mesh', 'convert_space',
                           'copy', 'draw', 'draw_color',
                           'dm_info', 'dupli_list_clear',
                           'dupli_list_create', 'find_armature', 
                           'is_deform_modified', 'is_modified', 'is_visible',
                           'is_duplicator',
                           'ray_cast', 'shape_key_add', 'select', 'to_mesh',
                           'update_from_editmode', 'update_tag', 
                           'user_clear', 'show_viewport', 'show_expanded',
                           'threads', 'threads_mode', 'is_dirty',
                           'cursor_location', 'output_node','quicktime',
                           'engine', 'show_keys_from_selected_only', 'filepath',
                           'mode', 'dimensions', 'border_min_x', 'border_max_x',
                           'border_min_y','border_max_y', 'is_saved', 
                           'file_extension', 'use_border', 
                           'use_shading_nodes', 'use_spherical_stereo','preview_render_type',
                           'users', 'view_center', 'tag',
                           'total_face_sel', 'total_vert_sel', 
                           'total_edge_sel', 'is_editmode', 'cr_node_index', 'cr_nodes',
                           'use_autopack'}
                           
obj_data_block_attribs = obj_data_block_attribs - black_list
mesh_data_block_attribs = mesh_data_block_attribs - black_list
subsurf_mods_attribs = subsurf_mods_attribs - black_list
node_attribs  = node_attribs - black_list     
vertex_data_block_attribs = vertex_data_block_attribs - black_list
polygon_data_block_attribs = polygon_data_block_attribs - black_list 
scene_data_block_attribs = scene_data_block_attribs - black_list  
light_settings_attribs = light_settings_attribs - black_list     
mist_settings_attribs = mist_settings_attribs - black_list
animation_data_attribs = animation_data_attribs - black_list
material_data_block_attribs = material_data_block_attribs - black_list
world_data_block_attribs = world_data_block_attribs - black_list
camera_data_block_attribs = camera_data_block_attribs - black_list
lamp_data_attribs = lamp_data_attribs - black_list
area_lamp_data_attribs = area_lamp_data_attribs | lamp_data_attribs - black_list
point_lamp_data_attribs = point_lamp_data_attribs | lamp_data_attribs - black_list
sun_lamp_data_attribs = sun_lamp_data_attribs | lamp_data_attribs - black_list
spot_lamp_data_attribs = spot_lamp_data_attribs | lamp_data_attribs - black_list
render_settings_attribs = render_settings_attribs - black_list
node_tree_data_block_attributes = node_tree_data_block_attributes = black_list
texture_data_block_attributes = texture_data_block_attributes - black_list
node_socket = node_socket -black_list
shader_node_attributes = shader_node_attributes - black_list
shader_node_attribute_attributes = shader_node_attribute_attributes - black_list
shader_node_bsdf_anisotropic_attributes = shader_node_bsdf_anisotropic_attributes -\
    black_list
shader_node_bsdfglass_attributes = shader_node_bsdfglass_attributes - black_list
shader_node_bsdfhair_attributes = shader_node_bsdfhair_attributes - black_list
shader_node_bsdfprincipled_attributes = shader_node_bsdfprincipled_attributes -black_list
shader_node_bsdfrefraction_attributes = shader_node_bsdfrefraction_attributes -black_list
shader_node_bsdftoon_attributes = shader_node_bsdftoon_attributes - black_list
shader_nodebump_attributes = shader_nodebump_attributes - black_list
shader_node_extendedmaterial_attributes = shader_node_extendedmaterial_attributes -\
    black_list
shader_node_geometry_attributes = shader_node_geometry_attributes - black_list
shader_node_mapping_attributes = shader_node_mapping_attributes - black_list
shader_node_material_attributes = shader_node_material_attributes - black_list
shader_node_math_attributes = shader_node_math_attributes - black_list
shader_node_normal_map_attributes = shader_node_normal_map_attributes - black_list
shader_node_outputlamp_attributes = shader_node_outputlamp_attributes - black_list
shader_node_output_material_attributes = shader_node_output_material_attributes - \
    black_list
shader_node_particleinfo_attributes = shader_node_particleinfo_attributes - black_list
shader_node_script_attributes = shader_node_script_attributes - black_list
shader_node_sss_attributes = shader_node_sss_attributes - black_list
shader_node_tangent_attributes = shader_node_tangent_attributes - black_list
shader_node_texbrick_attributes = shader_node_texbrick_attributes - black_list
shader_node_texcoord_attributes = shader_node_texcoord_attributes - black_list
shader_node_texenvironment_attributes = shader_node_texenvironment_attributes - black_list
shader_node_texgradient_attributes = shader_node_texgradient_attributes - black_list
shader_node_teximage_attributes = shader_node_teximage_attributes - black_list
shader_node_texmagic_attributes = shader_node_texmagic_attributes - black_list
shader_node_texmusgrave_attributes = shader_node_texmusgrave_attributes - black_list
shader_node_texpointdensity_attributes = shader_node_texpointdensity_attributes -\
    black_list
shader_node_texsky_attributes = shader_node_texsky_attributes - black_list
shader_node_texvoronoi_attributes = shader_node_texvoronoi_attributes - black_list
shader_node_texwave_attributes = shader_node_texwave_attributes - black_list
shader_node_texture_attributes = shader_node_texture_attributes - black_list
shader_node_tree_attributes = shader_node_tree_attributes - black_list
shader_node_uvalongstroke_attributes = shader_node_uvalongstroke_attributes - black_list
shader_node_uvmap_attributes = shader_node_uvmap_attributes - black_list
shader_node_vectormath_attributes = shader_node_vectormath_attributes - black_list
shader_node_vectortransform_attributes = shader_node_vectortransform_attributes -\
     black_list
shader_node_wireframe_attributes = shader_node_wireframe_attributes - black_list



# for attribs in obj_data_block_attribs:
    
              
attr_mapping = {
              'Scene': scene_data_block_attribs,
              'World': world_data_block_attribs,
              #'Object': obj_data_block_attribs, 
              'Mesh': mesh_data_block_attribs,
              'MeshVertex': vertex_data_block_attribs,
              'MeshPolygon': polygon_data_block_attribs,
              'SubsurfModifier' : subsurf_mods_attribs,
              'Node': node_attribs, 
              'RenderSettings': render_settings_attribs,
              #temporarily disabling compositing, at least 
            # until we support it properly anyway, JC.
#               bpy.types.CompositorNodeViewer: node_attribs,
#                    bpy.types.CompositorNodeAlphaOver:node_attribs,
#                    bpy.types.CompositorNodeBlur:node_attribs,
#                    bpy.types.CompositorNodeComposite:node_attribs,
#                    bpy.types.CompositorNodeMixRGB:node_attribs,
#                    bpy.types.CompositorNodeCurveRGB:node_attribs,
#                    bpy.types.CompositorNodeRLayers:node_attribs,
#                    bpy.types.CompositorNodeFilter:node_attribs,
            'WorldLighting':light_settings_attribs,
            'WorldMistSettings':mist_settings_attribs,
            'AnimData':animation_data_attribs,  
            'Material':material_data_block_attribs,
            'Camera':camera_data_block_attribs,
            'Lamp':lamp_data_attribs,
            'AreaLamp':area_lamp_data_attribs,
            'HemiLamp':lamp_data_attribs,
            'PointLamp':point_lamp_data_attribs,
            'SpotLamp':spot_lamp_data_attribs,
            'SunLamp':sun_lamp_data_attribs,
            'NodeTree':node_tree_data_block_attributes,
            'Texture':texture_data_block_attributes,
            'ShaderNodeAddShader': shader_node_attributes,
            'ShaderNodeAmbientOcclusion': shader_node_attributes,
            'ShaderNodeAttribute':shader_node_attribute_attributes,
            'ShaderNodeBackground': shader_node_attributes,
            'ShaderNodeBlackbody': shader_node_attributes,
            'ShaderNodeBrightContrast': shader_node_attributes,
            'ShaderNodeBsdfAnisotropic': shader_node_bsdf_anisotropic_attributes,
            'ShaderNodeBsdfDiffuse': shader_node_attributes,
            'ShaderNodeBsdfGlass': shader_node_bsdfglass_attributes,
            'ShaderNodeBsdfGlossy': shader_node_bsdfglossy_attributes,
            'ShaderNodeBsdfHair': shader_node_bsdfhair_attributes,
            'ShaderNodeBsdfPrincipled': shader_node_bsdfprincipled_attributes,
            'ShaderNodeBsdfRefraction': shader_node_bsdfrefraction_attributes,
            'ShaderNodeBsdfToon': shader_node_bsdftoon_attributes,
            'ShaderNodeBsdfTranslucent': shader_node_attributes,
            'ShaderNodeBsdfTransparent': shader_node_attributes,
            'ShaderNodeBsdfVelvet': shader_node_attributes,
            'ShaderNodeBump': shader_nodebump_attributes,
            'ShaderNodeCameraData': shader_node_attributes,
            'ShaderNodeCombineHSV': shader_node_attributes,
            'ShaderNodeCombineRGB': shader_node_attributes,
            'ShaderNodeCombineXYZ': shader_node_attributes,
            'ShaderNodeEmission': shader_node_attributes,
            'ShaderNodeExtendedMaterial': shader_node_extendedmaterial_attributes,
            'ShaderNodeFresnel': shader_node_attributes,
            'ShaderNodeGamma': shader_node_attributes,
            'ShaderNodeGeometry': shader_node_geometry_attributes,
            'ShaderNodeGroup': shader_node_attributes,
            'ShaderNodeHairInfo': shader_node_attributes,
            'ShaderNodeHoldout': shader_node_attributes,
            'ShaderNodeHueSaturation': shader_node_attributes,
            'ShaderNodeInvert': shader_node_attributes,
            'ShaderNodeLampData': shader_node_attributes,
            'ShaderNodeLayerWeight': shader_node_attributes,
            'ShaderNodeLightFalloff': shader_node_attributes,
            'ShaderNodeLightPath': shader_node_attributes,
            'ShaderNodeMapping': shader_node_mapping_attributes,
            'ShaderNodeMaterial': shader_node_material_attributes,
            'ShaderNodeMath': shader_node_math_attributes,
            'ShaderNodeMixRGB': shader_node_attributes,
            'ShaderNodeNewGeometry': shader_node_attributes,
            'ShaderNodeNormal': shader_node_attributes,
            'ShaderNodeNormalMap': shader_node_normal_map_attributes,
            'ShaderNodeObjectInfo': shader_node_attributes,
            'ShaderNodeOutput': shader_node_output_attributes,
            'ShaderNodeOutputLamp': shader_node_outputlamp_attributes,
            'ShaderNodeOutputLineStyle': shader_node_output_linestyle_attributes,
            'ShaderNodeOutputMaterial': shader_node_output_material_attributes,
            'ShaderNodeOutputWorld': shader_node_particleinfo_attributes,
            'ShaderNodeRGB': shader_node_attributes,
            'ShaderNodeRGBCurve': shader_node_attributes,
            'ShaderNodeRGBToBW': shader_node_attributes,
            'ShaderNodeScript': shader_node_script_attributes,
            'ShaderNodeSeparateHSV': shader_node_attributes,
            'ShaderNodeSeparateRGB': shader_node_attributes,
            'ShaderNodeSeparateXYZ': shader_node_attributes,
            'ShaderNodeSqueeze': shader_node_attributes,
            'ShaderNodeSubsurfaceScattering': shader_node_sss_attributes,
            'ShaderNodeTangent': shader_node_tangent_attributes,
            'ShaderNodeTexBrick': shader_node_texbrick_attributes,
            'ShaderNodeTexChecker': shader_node_attributes,
            'ShaderNodeTexCoord': shader_node_texcoord_attributes,
            'ShaderNodeTexEnvironment': shader_node_texenvironment_attributes,
            'ShaderNodeTexGradient': shader_node_texgradient_attributes,
            'ShaderNodeTexImage': shader_node_teximage_attributes,
            'ShaderNodeTexMagic': shader_node_texmagic_attributes,
            'ShaderNodeTexMusgrave': shader_node_texmusgrave_attributes,
            'ShaderNodeTexNoise': shader_node_attributes,
            'ShaderNodeTexPointDensity': shader_node_texpointdensity_attributes,
            'ShaderNodeTexSky': shader_node_texsky_attributes,
            'ShaderNodeTexVoronoi': shader_node_texvoronoi_attributes,
            'ShaderNodeTexWave': shader_node_texwave_attributes,
            'ShaderNodeTexture': shader_node_texture_attributes,
            'ShaderNodeTree': shader_node_tree_attributes,
            'ShaderNodeUVAlongStroke': shader_node_uvalongstroke_attributes,
            'ShaderNodeUVMap': shader_node_uvmap_attributes,
            'ShaderNodeValToRGB': shader_node_attributes,
            'ShaderNodeValue': shader_node_attributes,
            'ShaderNodeVectorCurve': shader_node_attributes,
            'ShaderNodeVectorMath': shader_node_vectormath_attributes,
            'ShaderNodeVectorTransform': shader_node_vectortransform_attributes,
            'ShaderNodeVolumeAbsorption': shader_node_attributes,
            'ShaderNodeVolumeScatter': shader_node_attributes,
            'ShaderNodeWavelength': shader_node_attributes,
            'ShaderNodeWireframe': shader_node_wireframe_attributes,
            'NodeSocketBool':node_socket,
            'NodeSocketColor':node_socket,
            'NodeSocketFloat':node_socket,
            'NodeSocketFloatAngle':node_socket,
            'NodeSocketFloatFactor':node_socket,
            'NodeSocketFloatPercentage':node_socket,
            'NodeSocketFloatTime':node_socket,
            'NodeSocketFloatUnsigned':node_socket,
            'NodeSocketInt':node_socket,
            'NodeSocketIntFactor':node_socket,
            'NodeSocketIntPercentage':node_socket,
            'NodeSocketIntUnsigned':node_socket,
            'NodeSocketShader':node_socket,
            'NodeSocketString':node_socket,
            'NodeSocketVector':node_socket,
            'NodeSocketVectorAcceleration':node_socket,
            'NodeSocketVectorDirection':node_socket,
            'NodeSocketVectorEuler':node_socket,
            'NodeSocketVectorTranslation':node_socket,
            'NodeSocketVectorVelocity':node_socket,
            'NodeSocketVectorXYZ':node_socket,
            'NodeSocketVirtual':node_socket
            
              
              }
              
attributes_map = {getattr(bpy.types, name, None):attributes\
                     for name, attributes in attr_mapping.items()
                     }
              