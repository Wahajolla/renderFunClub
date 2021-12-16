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

import bpy, sys, os

s = os.path.sep
user_preferences = bpy.context.preferences

cr_pkg = 'crowdrender'

# if this addon is already enabled, then there is no need 
# to enable it a second time.
if not cr_pkg in user_preferences.addons:
    bpy.ops.preferences.addon_enable(module = cr_pkg)
    
crowdrender = sys.modules[cr_pkg]

# get a ref to the crowdrender addon prefs so we can determine if debugging is on or not
addon_prefs = user_preferences.addons[cr_pkg].preferences

if addon_prefs.use_debug:

    try:
    
        ret = bpy.ops.preferences.addon_enable(module = "remote_debugger")
    
        if ret == {'CANCELLED'}:
            print("remote debugger could not be enabled, is it installed?")
    #     bpy.context.preferences.addons["remote_debugger"].preferences['pydevpath'] = \
    #     "/Applications/Eclipse.app/Contents/Eclipse/plugins/" +\
    #     "org.python.pydev_5.3.1.201610311318/pysrc/pydevd.py"
 
        else: 
            ret = bpy.ops.debug.connect_debugger_pydev()
        
            if ret == {"CANCELLED"}:
                print("remote debugger could not be enabled, the remote_debugger addon cancelled, "
                      "have you setup your path in user preferences?")
 
    except:
        print("could not start debugging environment, pls check remote_debugger ",
              "is enabled, you have configured the correct paths and the debug server",
              " is running")



#_______________ CONDITIONAL IMPORT BASED ON PACKAGE ___________________________________#

# for packages with source code
if s+'cr'+s in __file__:
    server_interface = crowdrender.src.cr.server_interface
    
    
elif s+'py_3_7'+s in __file__:
    server_interface = crowdrender.src.py_3_7.server_interface
    
elif s+'py_3_8'+s in __file__:
    server_interface = crowdrender.src.py_3_8.server_interface
    
elif s+'py_3_9'+s in __file__:
    server_interface = crowdrender.src.py_3_9.server_interface


machine_manager = server_interface.CRMachineManager()