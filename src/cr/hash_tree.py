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
hash_tree - Has objects to implement hash tree for graph based data structures.

Purpose

Before rendering, crowdrender has to check that each server node has 
exactly the same data and settings. The hash tree identifies very quickly 
if the data on any particular server node is the same as that of the client.
and allows us to update nodes that are out of sync with their client's data.


How

The objects in this module accept a CRRules object which contains a mapping
of parent : children. The CRHashTreeNode class uses this mapping to generate
a hash tree. This makes this module most suited to data that has a natural
graph like structure. It was initially designed to create a hash tree that 
would represent the state of data in a scene graph. 

Classes Exported - CRHashTree, CRHashTreeNode, 

Errors Raised - None (as yet)

Functions Exported - None

"""
# Note that by using a relative import here, we are binding the location 
# of the rules module to the crowdrender folder. If rules.py gets moved 
# its highly likely that this will break. 
import queue, os, sys
from collections import deque

from functools import reduce
import faulthandler

from . import rules
from . import utils, config
from . utils import  func_time, profile_func, get_base_app_version, setup_logging
from . logging import l_sep



####  CREATE CRASH LOGS #####


fault_text_file_path = os.path.expanduser("~") +\
     os.path.normpath("/cr/logging/hash_tree.txt")

if os.path.exists(fault_text_file_path):
    fault_text_file = open(fault_text_file_path, "wb")
else:
    utils.mkdir_p(os.path.split(fault_text_file_path)[0])
    fault_text_file = open(fault_text_file_path, "wb")
    
#Create logger instance

logger = setup_logging('hash_tree', create_stream_hndlr = False, 
            base_app = get_base_app_version())

        
class CRHashTreeNode:
    """ Implements a hash tree that represents a graph based data structure.
    
        This class implements a hash tree which has the following properties:
            - Recursively searches the data structure adding its own children
            - Recursively updates and hashes the nodes when called to update.
            - Actively searches the data structure for changes when a tagged
                condition does not result in a different hash. 

        Public Methods:
        
        calculate_hash - Calculates the hash of the node's data
        insert_child_node - instantiate and append a new CRHashTreeNode 
            to the list of children
        parse - traverses the data of the node search for and 
            adding child nodes.
        update - calls the CRRules.update method to check for tagged status
            and then recursively calls the CRRules.update of the updated 
            node's children. 
        
        Public data variables:
        
        parent - CRHashTreeNode: pretty obvious, the parent of this node
        data - Unknown type:again fairly obvious
        type - Class: the class of the data object
        rules - CRRules: The rules object created by this particular node
        data_hash_value - int: the hash calculated on just the attributes of the 
            data object
        hash_value - int: the aggregate hash value of all descendants of this node
            so children's children's children and so on. 
        name - str: Some data objects give them selves an internal name, if one
            is defined it should be assigned to by the CRRules.get_name
            method.
        
        
    
    """
    
        
    
    def __init__(self, data, parent, hash_tree, hash_rules=rules.CRRules,
                item_of=None):
        self.parents = []
        if not parent is None: self.parents.append(parent)
        self.hash_tree = hash_tree
        self.data = data
        self.children = list()
        self.length = 0
        self.rules = hash_rules
        self.pointer = self.rules.get_ref(self.data)
        self.data_hash_value = 0
        self.hash_value = 0
        self.hash_mod = 65521
        self.name = self.rules.get_name(self.data)
        self.item_of = item_of
        self.logger = hash_tree.logger
        
        uuid_unique = False
        
        
        
        if not len(self.parents) < 1:
        
        # to ensure uniqueness, we prefix the uuid with that of its ancestors,
        # not perfect, and certainly not pretty when printed, but it ensures that 
        # nodes stored in our nodes_by_uuid collection will be unique.
            self.uuid = ''
        
            for parent in self.parents:
            
                self.uuid += parent.uuid 
                
            if not self.item_of is None:
            
                self.uuid += "::" + self.item_of + "::" + self.rules.get_uuid(self.data)
            
            else:
                
                self.uuid += "::" + self.rules.get_uuid(self.data)
                
        else:
            self.uuid = self.rules.get_uuid(self.data)
        # DANGER, we should check to see that data has any attribute we
        # are querying before we access it. We could easily generate an 
        # unhandled exception this way.
        while not uuid_unique:
            
            uuid_unique = False
            counter = 0
            
            if self.uuid in self.hash_tree.nodes_by_uuid:
                
                counter += 1
                self.uuid += "{0:0=2d}".format( counter )
        
            else:
                
                uuid_unique = True
            
                # Add our new node to the nodes_by_uuid dictionary, used on the
                # server session process to find a node by its uuid
            
                self.hash_tree.nodes_by_uuid[self.uuid] = self
            
            
        
        
        # Add this node to the hash_tree's list of instantiated nodes
                
        self.hash_tree.nodes[self.data.as_pointer()] = self
        
        
        # Get the data type we're interested in, this isn't always as simple
        # as calling 'type()' on the object, if we do this on a collection
        # all we get is the type of the collection. We want the application
        # specific code to tell us what type we have rather than guess.
        
        self.type = self.rules.get_type(self.data)
        
        # Add our new node to the reference of nodes indexed by data type.
        # This allows us search for nodes of a particular type.
        
        self.hash_tree.nodes_by_type[self.type] = self
        
        
        
                
        # here we have grabbed all the attributes of the node object
        # so we don't have to re-grab them each time we hash the node data.
             
        self.attributes = self.rules.get_attribs(self.data)
        self.attrib_hashes = {}
        
        # for hashing and detecing attribute changes, we build a dictionary
        # to hold the hashes of each attribute.
        
        for name in self.attributes:
            self.attrib_hashes[name] = self.attributes[name]
        
        
        
        
    def insert_child_node(self, data=None, node=None, append=False, item_of = None):
        """ creates a new node and appends it to the parent's list of children.
        
        Methodology:
        
        Creates a new instance of CRHashTreeNode and appends it to the owning
        objects self.children list. If the append argument is true, 
        
        arguments: data_or_node - name, 
            pointer or ref to the data being represented, or an already 
            existing node. In the latter case you need to set append to True.
            
            append=False - boolean, set to true if you are inserting a node
            that already exists. This occurs with diamond shaped graph data
            structures.
            
        return value: None
        side effects: appends a CRHashTreeNode to the self.children list of 
            the owning object.
        exceptions raised: None
        restrictions: Unknown
        """
        
        # If we are adding a node that already exists, simply append it
        # to the list of children, there's no need to instantiate another
        # node.
        
        if append:
            # If this node is already listed as a child, we have no need to 
            # add it again. We simple return the node and exit. 
            # Otherwise we append it to the list of children and parse it.
            
            if not node in self.children:
                # add this node as a parent
                node.parents.append(self)
                
                # append the existing node to this node's children
                self.children.append(node)
                # data_or_node.parse(initialising=True)
            # print("searching :", node.name)    
            
            
            
            return node
        
        else:
            #print("WOWZA!!, we're adding a new node", " : ", type(data.bl_rna))
            
            new_node = CRHashTreeNode(data, self, self.hash_tree, self.rules, 
                                    item_of=item_of)
            
            self.children.append(new_node)
            
            return new_node
         
        
    #@func_time    
    def search_data(self, invalidated, initialising=False):
        """ Call CRRules parse method, optional call to self.calculate_hash
        
        Methodology:
        
        Calls the CRRules.parse method, if the optional keyword argument
        is true, the calculate_hash method is also called.
        
        arguments: 
            invalidated     - collection:   A python list that contains all nodes that
                                        potentially have changed their hash value and 
                                        require the value to be aggregated upwards
            initialising    - booolean:     True if the hash tree is being rebuilt
                                        otherwise it is false.
                                        
        return value: 
            None
        side effects: 
            Calls CRRules.parse and optionally calculate_hash
        exceptions raised: 
            None
        Description:
            Search data is responsible for finding new objects or data within the host 
            application's session. It does this by consulting the parse func, defined by
            the rules module, that describes the object types that are expected to 
            be in the session and how they link to each other. 
            
            As each node is processed, it in turn calls its search data function, which 
            means that the session data is processed recursively. Each node adds a ref 
            to its self in the invalidated collection as it is processed. This collection
            then determines a subset of all nodes that was processed for aggregating to 
            build the hash tree value. This drastically reduces the number of nodes that
            are processed each time the user confirms an edit.  
             
        
        """
        get_ref = self.rules.get_ref
        # if we are re-parsing due to an inconsistency, its cleaner
        # to remove the current list of children and re-populate with a 
        # fresh parse, prob saves on memory too! This effectively means
        # we are always initialising when we parse or re-parse. However 
        # its felt that this is more consistent and less tricky to manage.
        
        invalidated.append(self)
        
        if initialising:
            
            for child in self.children:
 
                child.delete(del_branch=True)
                
            self.children.clear()
            
            hash_value = self.calculate_hash(initialising)
            
            ## SEARCH FOR NODES
            # Looks in the attributes of this node to find its nodes if they're there.
            
            new_data = self.rules.parse(self.data)

            
            for data in new_data:
            
                existing_node = self.hash_tree.nodes.get(get_ref(data[0]))
                
                if existing_node is not None and existing_node in invalidated:
                    
                    hash_value += existing_node.hash_value
            
                elif existing_node is not None:
                
                    node = self.insert_child_node(node = existing_node, append = True, 
                        item_of = data[1])
                        
                    hash_value += node.search_data(invalidated, initialising)
                    
                else:
                    node = self.insert_child_node(data = data[0])
                
                    hash_value += node.search_data(invalidated, initialising)
            
                
        # if we are not initialising then we are scanning an existing node
        # for new children.
        
        else:
            
            hash_value = self.calculate_hash()
            
            new_data = self.rules.parse(self.data)
            
            for data in new_data:
            
                existing_node = self.hash_tree.nodes.get(get_ref(data[0]))
                
                if existing_node is not None and existing_node in invalidated:
                    
                    hash_value += existing_node.hash_value
            
                elif existing_node is not None:
                
                    node = self.insert_child_node(node = existing_node, append = True, 
                        item_of = data[1])
                    
                    hash_value += node.search_data(invalidated)
                    
                else:
                    node = self.insert_child_node(data = data[0])
                    
                    hash_value += node.search_data(invalidated)
            
                    
        ## CONTINUE OR TURN AROUND AND AGGREGATE?
        # after finding all the data that we can, and creating child nodes, we now
        # check to see if the hash value is different. If it is, we need to aggregate
        # upwards to propagate the value to the top of the tree.
        
        if self.hash_value != hash_value:
            
            self.hash_value = hash_value
            
            for parent in self.parents:
                parent.aggregate_hash_values()
                
        
                
        # eventually, we need to return the hash value to the parent who called 
        # search data on this node. 
                
        return self.hash_value
            
            
                
        
    def uuid_change(self):
        """ Update the uuid of the node when the user has changed the data's name
        
        When a user updates the name of an object or other id block, we need to 
        update the corresponding node's uuid.
        """
        
        old_uuid = self.uuid
        
        self.uuid = self.rules.get_uuid(self.data)
        
        self.hash_tree.nodes_by_uuid[self.uuid] =\
            self.hash_tree.nodes_by_uuid.pop(old_uuid)
        
        self.hash_tree.sync_queue.put( 
                        attributes = {utils.node_uuid:old_uuid, 
                                    utils.new_uuid:self.uuid}
                                                  )
            

    
    # @utils.func_time    
    def calculate_hash(self, initialising=False):
        """Calculates the hash for the current node_data
        
        Methodology:
        
        Each node stores a reference to the data it represents, the hash 
        algorithm attempts to hash each attribute of the node's data in turn
        by reference to the CRRules object of this method's class. See that
        object for the implementation. 
        
        arguments: initislising=False 
        return value: None
        side effects: sets owning class's self.hash_value attribute
        exceptions raised: None
        restrictions: Unknown
        
        """
        
        
        temp_hash_value = self.data_hash_value
        
        self.data_hash_value = 0
        
        hash = self.rules.hash
        attributes = self.attributes
        items = attributes.items
        attrib_hashes = self.attrib_hashes
        data_hash_value = self.data_hash_value 
        hash_values = {}
        
                
        # objects which are collections are not hashed, these objects
        # usually implement an __iter__ function. We filter out these
        # collections.
        
        if not hasattr(self.data, '__iter__'):
            
            #IDEA!!! why not have the rules object return a function that 
            # can be used below in the for loop, that way we are not calling
            # two functions each time we hash an attribute. We just call 
            # the function that gets hashed.
            
            # ANOTHER IDEA!! why not put the code below in another process?
            # we could consider using the multiprocessing module to offload
            # the main blender process (which when processing our code only 
            # one CPU, core, threading unit).
            
            if initialising:
                
                # use map to create a dict of hash values
                hash_values = {name:hash(value) for name, value in items()}
                
                #Needed for comparison later on
                self.attrib_hashes = hash_values
                
                # convert this to a list so we can use it in reduce to computer the 
                # data hash
                list_hash_values = list(hash_values.values()) # append at least a 0 value 
                        # or reduce errors on the empty list we get sometimes
                        
                list_hash_values.append(0)
                
                # reduce gives the sum of all has values and we're done
                data_hash_value = sum(list_hash_values)
                
                
                
            elif not initialising:
                
                # self.hash_tree.logger.info("About to get attribs in calculate_hash")
                # self.hash_tree.walk(logger=self.hash_tree.logger)
                
                attribs_to_sync = []
                append = attribs_to_sync.append
                               
                attributes = self.rules.get_attribs(self.data)
                self.attributes = attributes
                
                
                for names in attributes:
                    # Temporary variable below needs to be removed
                    temp_data = hash(attributes.get(names))
                    
                    
                                        
                    if temp_data != attrib_hashes.get(names):
                        append((names, attributes[names],))
                        attrib_hashes[names] = temp_data
                    
                    data_hash_value += temp_data
                    
                    # print(self.data, " :: " , names, " :: " , temp_data, " :: " , self.attributes[names])
                    
                #since we use the attributes name_class pattern as a uuid, we need to
                # update this each time the user changes the name of an object.
                    
                if any(attribs_to_sync):
                
                    for attrs in attribs_to_sync:
                
                        self.hash_tree.sync_queue.put( 
                                                {utils.node_uuid:self.uuid, 
                                                utils.attributes:attrs[0], 
                                                utils.value:attrs[1]}
                                                      )
            
            self.data_hash_value = data_hash_value #int types are not assigned by 
                            # reference, changing data_hash_value, which is local 
                            # to this scope, doesn't affect self.data_hash_value
                            # which is critical to the whole hash thing
    
        return data_hash_value
        
    #End of calculate_hash()
    
            
    def aggregate_on_build(self):
    
        """ Aggregate hash values downwards through the hash tree 
        
        Arguments:
            None
        Returns: 
            int:    - hash value of the node plus its descendants
        Side Effects:   
            Calls recursively down through the hash tree
        Exceptions:
            none
        Description:
            After much testing it was discovered that this method is orders of magnitude
            faster at aggregating when completely rebuilding the hash tree. 
            This is probably due to the fact that the invalidate-aggregate method
            requires two passes, one to invalidate and one to aggregate upwards.
            This method requires only one pass. 
                    """
        
        hash_value = self.data_hash_value
        
        for child in self.children:
            
            hash_value += child.aggregate_hash_values()
            
        self.hash_value = hash_value
        
        return self.hash_value
    
            
    def aggregate_hash_values(self):
    
    
        ## CALCULATION PART
        # Find the new hash value for this node, done by summing over children's hash
        # values
        
        
        
        hash_value = self.data_hash_value
        
        if self.children:
            
            # in order to get the reduce function to work, the first item in the 
            # list needs to be an int, this is because in reduce, the first argument
            # needs to be an int where the accumulated total is stored, the second
            # argument is the update which is where the hash_value comes from
            
#             hash_values = [child.hash_value for child in self.children]
#             
#             hash_value += sum(hash_values)
        
            # hash_value += reduce(
#                         (lambda x, y: x + y.hash_value), self.children, 0)
                
            for child in self.children:
            
                hash_value += child.hash_value
            
        self.hash_value = hash_value
        
        ## RECURSIVE PART
        # Call each parent recursively to aggregate until the tree root node is reached
        for parent in self.parents:
        
            parent.aggregate_hash_values()
#         map([parent.aggregate_hash_values for parent in self.parents], self.parents)
        
        return self.hash_value
    
    def delete(self, del_branch=False):
        """ removes this node plus its dependents from the hash tree
        
        TODO:JIRA:CR-42 Really need to think more about the flow on effects from
        recursively removing dependents. Where an object data block has
        a mesh as a child, deleting the object would cause the mesh block 
        to have no parents, this could (providing the mesh is not used 
        by another object) cause the mesh to be redundant and removed, this
        in turn could cause the mesh's vertices, edges and faces to be
        removed and so on. This could cause a considerable delay which 
        may be noticeable by the user. Ideally, we'd want to have a method
        which would only process a maximum number of removals before returning 
        give the user interface a refresh. 
        """
        if del_branch:
            
            self.hash_tree.nodes.pop(self.pointer, None)
                                                        
            self.hash_tree.nodes_by_uuid.pop(self.uuid, None)
    
            self.hash_tree.nodes_by_type.pop(self.type, None)
            
            for child in self.children:
                child.parents.clear()
                child.delete(del_branch = True)
                
            self.children.clear()
            
                
        else:
            
            self.hash_tree.nodes.pop(self.pointer, None)
                                                        
            self.hash_tree.nodes_by_uuid.pop(self.uuid, None)
    
            self.hash_tree.nodes_by_type.pop(self.type, None)
                
                
            for child in self.children:
                child.parents.remove(self)
            
            
            for parent in self.parents:
                parent.children.remove(self)   
            
        
            
    #End of delete()       
            
class CRHashTree:
    """ Implement that containing object for the CRHashTreeNodes.
    
    The CRHashTree is a container for the root node and top hash. It 
    represents a unique state of the data structure being tracked. The 
    top hash is a proxy for this state. Refer to the docstrings of the 
    CRHashTreeNode and CRRules classes for further details.
    
    Public Methods:
        
    parse_main - Create a new root node
    update_hashtree - Compute a new top hash based on the changed data
        
        
    Public data variables:
    
    data - Unknown type: data object reference
    tree_root - CRHashTreeNode: Represents the root of the data structure.
    top_hash - int: the hash for the entire data structure being tracked. 
        
    
     
    """
        
    
    
    def __init__(self, data, rules):
    
        self.logger = logger
        self.data = data
        self.rules = rules
        self.tree_root = None
        self.top_hash = 0
        self.nodes = {}
        self.nodes_by_type = {}
        self.nodes_by_uuid = {}
        self.sync_queue = queue.Queue()
        self.msg_queue = queue.Queue()
        
        self.undo_array = deque() 
        
        
        self.parse_main(data)
        
        #self.undo_array.append(self.top_hash)### establish the undo array to hold ref's to the 
        # current undo state plus other states we're going to push to 
        
    def delete_node(self, node_uuid=[], node_pointer=[]):
        """ Delete the node specified by the arguments
        
        Description
        
        This method removes a node according to the given arguments. 
        
        Arguments:
        node_uuid: the unique identifier for a node
        node_pointer: the last known pointer to the data of the node
        
        returns: an integer, 1 or -1, 1 indicates successful 
            processing, -1 is an error condition, the node could not be found.
        
        """
        
        nodes = []
        
        if node_uuid:
            #Build a list of nodes using the uuid's given.
            for item in node_uuid:
                if item in self.nodes_by_uuid:
                    nodes.append(self.nodes_by_uuid[item])
                    
        elif node_pointer:
            #Build a list of nodes using the pointers given.
            for item in node_pointer:
                if item in self.nodes:
                    nodes.append(self.nodes[item])
         
        else:
            #this is an error condition, the nodes cannot be found.
            # we need to log this.
                                   
            self.logger.warning("CRHashTree.delete_node: " + l_sep +\
                "this node could not be found in the tree, uuid: " +\
                str(node_uuid) + "  pointer: " + str(node_pointer))
                
            result = -1
        
        parents = {}
        
        if nodes:
            
            for node in nodes:
                
                node_parents = node.parents.copy()
                for parent in node_parents:
                    parents[parent.uuid] = parent
                #NOTE, get the parents before you delete the node! Obviously! 
                node.delete()
        
        for parent_node in parents.values():
            parent_node.search_data([], initialising= True)
            
        self.update_hashtree()

        
        result = 1
        
        return result
        
        
     
    def update_node(self, initialising, node_uuid='', node_pointer=0):
        """ Return a new top hash and list of updated nodes
        
        Description:
        This method takes as arguments the uuid or pointer necessary to id a node
        in the hash tree and then performs a search on that node to determine if its
        data hash changed. A new hash is calcualted and all hash values are then 
        aggregated to the top of the tree to arrive at the new value for the top hash.
        
        Nodes that have different values report in the returned value what attributes 
        changed and what their values are. 
        
        """
        #locate the node being updated
        if not node_pointer == 0:
            node = self.nodes.get(node_pointer)
        elif not node_uuid == '':
            node = self.nodes_by_uuid.get(node_uuid)
            
        else:
            node = None
        
        if not node is None:
            node.search_data([], initialising = initialising)
            
            
        # self.tree_root.aggregate_hash_values()
        
        return self.update_hashtree()


#         
    def undo_history_change(self, data):
        """ handle a change to the undo state of the data
        """
        # first re-process the data, all pointers are now invalid so
        # we have to rebuild the entire tree.
        
        #rebind to the new data here, it could now have changed mem address,
        # if we refer to it later we'll have an access violation
        self.data = data
        
        #first we find the index of the current top hash for our
        # starting point prior to applying the undo. 
        
        old_state_ind = self.undo_array.index(self.top_hash)
        
        self.parse_main(self.data, rebind=True)
        
        # the hash tree, now updated contains the latest hash, we 
        # query it to discover where in the undo history it is
        try:
            current_state_ind = self.undo_array.index(self.top_hash)
            
                #TODO: use cases, 1.perform an action, undo
            # 2. Perform an action, undo, redo
            # 3. toggle indecisively undo, redo, undo... cause you can
        
            if current_state_ind < old_state_ind:
            # This was an undo
                return -1
            elif current_state_ind > old_state_ind:
            # this was a redo
                return 1
            else:
            # No change
                return 0
                
        except:
        
            self.logger.warning("error, couldn't find current undo state in array")
            
            return 0
        
            
            
        
        
    
    def synchronise_tree(self):
        """ Send a SyncUpate object to the msg queue
        
        """
        
        #In theory this works, however, there is a 
        # risk of getting ones wires crossed since we 
        # also generate syncupdate objects in the client
        # which also puts them into the msg_queue. 
        # What we have here are two different methods being
        # employed to update the servers. The reason for the two 
        # methods is that the hash_tree is very good at detecting
        # and creating updates for modifications to attributes of
        # existing data. It knows all the existing data and what
        # the current state of it is. 
        # The client, on the other hand, gets first notice of additions 
        # of data via operators and then instructs the hash_tree to
        # add the new data to its self.
        # TODO:JIRA:CR-43: have a more rigorous approach to capturing data updates
        # that involves only one method or module rather than two. This
        # is for debugging and maintainability.
    
        
        while not self.sync_queue.empty():
        
            sync_item = self.sync_queue.get()
            
            sync_item.attributes[utils.top_hash] = self.top_hash
            sync_item.command = utils.data_update
            
            self.msg_queue.put(sync_item)
            # print("processing queue item :",
                        # sync_item.uuid,
                        # "attribute ",
                        # sync_item.attribute, 
                        # "with value ", 
                        # sync_item.value)
                        
                        
            self.sync_queue.task_done()
            
 
        
    def walk(self, children=None, node_level=0, logger=None):
        """
        
        Recursively print the nodes of the hash tree to display its contents.
        
        
        """
        # 0 is the root
        
        if children is None:
            children = self.tree_root.children
        
        title = 'ROOT '
        
        for i in range(0, node_level):
                title = title + '->.'
        
        node_level += 1
        
        for child in children:
            node_description = child.uuid + \
                 " :hash:" + str(child.hash_value) + " :data_hash:" + \
                str(child.data_hash_value)
            output = title + node_description
            if not logger is None:
                logger.info(output)
            else:
                print(output)
            self.walk(child.children, node_level, logger)
                
            
        
        
    
    
    def parse_main(self, data, rebind=False):
        """ Instantiate a root node using CRHashTreeNode
        
        Methodology:
        
        Simple, create a new instance of CRHashTreeNode and pass a ref
        of the root of the data structure to it. 
        
        arguments: rebind= False
        return value: None
        side effects: Creates a new CRHashTreeNode which in turn recursively 
            parses the entire data structure creating further nodes.
        exceptions raised: None
        restrictions: Unknown
        
        """
        #internal variables
            
        # So there are a couple of use cases for this function. First there is the 
        # initial creation of the tree which includes parsing blender's internal
        # data and creating a new tree. Then there is additions and deletions which
        # require another sweep of the current tree and its underlying data to see 
        # what has changed.
        
        #uhoh, there is no root, the first time the add-on is used
        # with a blend file/session, we'll need to construct a new tree
        # this is how we detect it. 
        if self.tree_root is None:
        
            self.tree_root = CRHashTreeNode(self.data, None, self, self.rules)
            
            self.tree_root.search_data([], initialising=True)
            
            print("hash_tree created")
            
        
        # In an UNDO/REDO situation, the safest thing to do is to 
        # simply invalidate the whole tree and re-parse all the data. This
        # is more computationally expensive, but will always produce correct 
        # results. 
        
        elif rebind:
        
            self.nodes.clear()
            self.nodes_by_type.clear()
            self.nodes_by_uuid.clear()
            
            self.tree_root = CRHashTreeNode(self.data, None, self, self.rules)
            
            self.tree_root.search_data([], initialising=True)
            
            
            print("hash_tree rebound")
        
        
            # #Heidegger, "waiting for the gift has come to seem like 
            # # mere weakness"
            
        self.update_hashtree()
        
        print("Crowdrender: number of hash tree nodes: ",len(self.nodes))
        print("Crowdrender: mem usage for hash tree: ", 
            sys.getsizeof(self.nodes) +\
            sys.getsizeof(self.nodes_by_uuid) +\
            sys.getsizeof(self.nodes_by_type)
            )
       
    #@utils.func_time    
    def update_hashtree(self, node=CRHashTreeNode):
        """ callback for updates to the data system
        
        Methodology:
        
        Simple, create a new instance of CRHashTreeNode and pass a ref
        of the root of the data structure to it. 
        
        arguments: client - a reference to the calling client's object
        return value: list containing updated nodes or none if no nodes updated
        side effects: calls the update method of the root node. 
                        updates the undo_array and changes the top hash value.
        exceptions raised: None
        restrictions: Unknown
        
        """
        # To tell if the hash changed on this update, store the current
        # value in a temp variable, update the hash and compare the results.
        
        
        temp_top_hash = self.top_hash
        
        
        self.top_hash = self.tree_root.hash_value
        

        
        updated_nodes = list()
        
        if temp_top_hash != self.top_hash:
        
            print('top hash changed, new value: ', self.top_hash)
            
            
            self.undo_array.append(self.top_hash)
            
            while not self.sync_queue.empty():
                
                updated_nodes.append(self.sync_queue.get())
            
        if len(updated_nodes)>0:        
            return (updated_nodes, self.top_hash)
        else:
            return (updated_nodes, self.top_hash)
            
            
import collections
            
class CRSet(collections.Sequence):
    
    def __init__(self, iterable=[]):
        self.elements = []
        for value in iterable:
            if value not in self.elements:
                self.elements.append(value)
                
        #self.node = node
        
    def __iter__(self):
        
        return iter(self.elements)
    
    def __contains__(self, value):
    
        return value in self.elements
        
    def __len__(self):
        
        return len(self.elements)
    
    def __getitem__(self, value):
        return self.elements[value]
    
    def __repr__(self):
        string = ''
        for element in self.elements:
            string += str(element) + ' '
        return string
        
    def append(self, value):
        
        self.elements.append(value)
        
    def remove(self, value):
    
        self.elements.remove(value)
    
    def clear(self):
        
        self.elements.clear()
