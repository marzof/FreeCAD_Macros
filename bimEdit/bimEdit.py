#!/usr/bin/env python3 
# -*- coding: utf-8 -*-

#*******************************************************************************
#*  (c) Marco Ferrara - https://github.com/marzof/ - 2019                      *
#*                                                                             *
#*  This program is free software: you can redistribute it and/or modify       *
#*  it under the terms of the GNU General Public License as published by       *
#*  the Free Software Foundation, either version 3 of the License, or          *
#*  (at your option) any later version.                                        *
#*                                                                             *
#*  This program is distributed in the hope that it will be useful,            *
#*  but WITHOUT ANY WARRANTY; without even the implied warranty of             *
#*  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the              *
#*  GNU General Public License for more details                                *
#*                                                                             *
#*  You should have received a copy of the GNU General Public License          *
#*  along with this program.  If not, see <https://www.gnu.org/licenses/>.     *
#*                                                                             *
#*******************************************************************************

## FreeCAD Macro BimEdit

## This macro intends to implement some useful behaviour for basic
## transfomations.
##
## Notably it let the user choose which are the elements to include in the 
## operations (the element itself, its base, itself and its additions...) and
## improve copy process for based elements and elements with additions.
##
## To make selection process easy and clear, objects involved in transformation
## are highlighted: beyond the chosen objects and their direct dependencies,
## it highlight (in a lighter way) the dependencies due to parameter 
## expressions.
## 
## This tool is (being) made for Arch objects only. It was not tested on other 
## type of entities.
##
## You can select the elements before or after launching the command.
## Then you can:
## - cycle between selection types pressing Ctrl + Space
## - Press q to stop the selection cycle and quit the command
## - when selection is ok you can launch the transformation pressing:
##      - g -> to move
##      - r -> to rotate
##      - (scale, mirror and stretch will come)


import FreeCAD, FreeCADGui, Draft
from DraftGui import translate, utf8_decode
from DraftTools import Modifier, msg, selectObject
from DraftTrackers import Tracker, ghostTracker
import re
from pivy import coin
from pivy.coin import *

from bimEdit_overrides import bimMove, bimRotate

### Utilities ###

def traverse_node(node, out=''):
    ''' Print the coin representation for all the children of selected object
    (for testing purpose only) '''
    if not node.getChildren():
        pass
    else:
        for nd in node.getChildren():
            print(out + str(nd))
            traverse_node(nd, out+'\t')

## obj = FreeCADGui.Selection.getSelection()[0]
## objNode = obj.ViewObject.RootNode
## traverse_node(objNode)

normalizeNormal = lambda obj: obj.Normal if obj.Normal != FreeCAD.Vector(0,0,0) \
        else FreeCAD.Vector(0,0,1)

pickSelection = lambda sel, sel_type: \
        [o for o in sel if o.selectionType == sel_type]

def selectionOption(sel=[]):
    ''' Entities are collected as four lists: 
     - normal (nothing happens to them)
     - to edit (actual editing objects), 
     - directed dependencies (objects based on selection),
     - expressions dependencies (dependencies called by expressions) '''

    return {
        '0_obj': {
            'normal': pickSelection(sel, 'addition') + \
                    pickSelection(sel, 'main_base'),
            'toEdit': pickSelection(sel, 'main'),
            'dirDeps': [],
            'exprDeps': pickSelection(sel, 'main_dependency'),
            'print' : 'The OBJECTS you clicked will be edited.\n' + \
                    'Eventually bases and additions will not be affected. ' + \
                    'Copies will point to the same bases'
            },
        '1_obj_base': {
            'normal': pickSelection(sel, 'addition_base') + \
                    pickSelection(sel, 'main_dependency') + \
                    pickSelection(sel, 'addition'),
            'toEdit': pickSelection(sel, 'main_base'),
            'dirDeps': pickSelection(sel, 'main'),
            'exprDeps': pickSelection(sel, 'main_base_dependency'),
            'print' : 'The BASES of the OBJECTS you clicked will be edited.' + \
                    '\nDirected dependencies, like the objects that are ' + \
                    'based on them, will be affected. Copying will create ' + \
                    'new bases and new objects based on them'
            },
        '2_obj_addition': {
            'normal': pickSelection(sel, 'addition_base') + \
                    pickSelection(sel, 'main_base'),
            'toEdit': pickSelection(sel, 'main') + \
                    pickSelection(sel, 'addition'),
            'dirDeps': [],
            'exprDeps': pickSelection(sel, 'main_dependency') + \
                    pickSelection(sel, 'addition_dependency'),
            'print' : 'The OBJECTS you clicked and their ADDITIONS will ' + \
                    'be edited.\nEventually bases will not be affected. ' + \
                    'Copies will point to the same bases'
            },
        '3_obj_addition_base': {
            'normal': pickSelection(sel, 'main_dependency'),
            'toEdit': pickSelection(sel, 'main_base') + \
                    pickSelection(sel, 'addition_base'),
            'dirDeps': pickSelection(sel, 'main') + \
                    pickSelection(sel, 'addition'),
            'exprDeps': pickSelection(sel, 'main_base_dependency') + \
                    pickSelection(sel, 'addition_base_dependency'),
            'print' : 'The BASES of the OBJECTS you clicked and ' + \
                    'their ADDITIONS will be edited.\n' + \
                    'Directed dependencies, like the objects that are ' + \
                    'based on them, will be affected. Copying will create ' + \
                    'new bases and new objects based on them. ' + \
                    'Relations between additions will be maintained'
            }
    }

selectionVisibility = { ## Attributes for different selection conditions
        'Transparency': {'toEdit': .80, 'dirDeps': .80, 'exprDeps': .80},
        'LineTransparency': {'toEdit': .0, 'dirDeps': .0, 'exprDeps': 1.0},
        'LineWidth': {'toEdit': 3, 'dirDeps': 1, 'exprDeps': 1},
        'FaceLineWidth': {'toEdit': 2, 'dirDeps': 1, 'exprDeps': 1},
        'LineColor': {'toEdit': (1.0,1.0,1.0), 'dirDeps': (1.0,1.0,1.0), 
            'exprDeps': (1.0,1.0,1.0)},
        'FaceColor': {'toEdit': (1.0,.0,.0), 'dirDeps': (1.0,.0,.0), 
            'exprDeps': (1.0,.0,.0)},
        }

hideAttribute = { ## Attributes for temporarily hiding objects
        'Transparency': 100,
        'DisplayMode': 'Wireframe',
        'LineWidth': 1.0
        }

######

class multiGhostTracker(ghostTracker):
    ''' Create a ghost from a copy of the coin representation of the object 
    (sep) according to the type (typ) of selection '''
    
    def __init__(self, obj, sep, typ):
        super().__init__(obj)
        ## First child of ghost is SoTransform and has to be kept, second child 
        ## is the actual container (SoSeparator) and will be replaced
        self.children = [self.children[0]]
        self.node = sep
        if typ is not 'normal':
            ## Create a SoAnnotation container to put the ghost on foreground
            self.node = SoAnnotation()
            self.node.addChild(sep)

            lineColor = selectionVisibility['LineColor']
            faceColor = selectionVisibility['FaceColor']

            transparency = selectionVisibility['Transparency']
            lineTransparency = selectionVisibility['LineTransparency']
            lineWidth = selectionVisibility['LineWidth']
            faceLineWidth = selectionVisibility['FaceLineWidth']

            search = coin.SoSearchAction()
            search.setInterest(search.ALL )
            search.setSearchingAll(True)
            SoBaseKit.setSearchingChildren(True)

            variations = {
                    SoIndexedFaceSet: {
                        'transparency': transparency,
                        'lineWidth': faceLineWidth},
                    SoIndexedLineSet: {
                        'transparency': lineTransparency,
                        'lineWidth': lineWidth},
                    SoPointSet: {
                        'transparency': lineTransparency,
                        'lineWidth': lineWidth}
                    }

            for sub_ob in variations:
                search.setType(sub_ob.getClassTypeId())
                search.apply(sep)
                paths = search.getPaths()
                for path in paths:
                    if path:
                        parent = path.getNodeFromTail(1)
                        for ch in parent.getChildren():
                            if ch.isOfType(SoMaterial.getClassTypeId()):
                                ch.diffuseColor.getValues()[0].setValue(
                                        lineColor[typ])
                                ch.transparency.setValue(
                                        variations[sub_ob]['transparency'][typ])
                                ch.emissiveColor.getValues()[0].setValue(
                                        faceColor[typ])
                            if ch.isOfType(SoShapeHints.getClassTypeId()):
                                ch.vertexOrdering.setValue(1)
                            if ch.isOfType(SoDrawStyle.getClassTypeId()):
                                ch.lineWidth.setValue(
                                        variations[sub_ob]['lineWidth'][typ])


        self.children.append(self.node)

        Tracker.__init__(self,dotted=False,scolor=None,swidth=None,
                children=self.children,name="ghostTracker")

class SelectedObject:
    ''' A class to get all the connection between selected objects and their
    bases, additions and dependencies.'''

    def __init__(self, obj, sel=[], sel_type='main', parent=None):
        self.obj = obj
        self.name = obj.Name
        self.selectionType = sel_type
        self.base = self.setBase(obj, sel)
        self.isDependency = True if 'dependency' in self.selectionType \
                else False
        self.parent = parent
        self.additions = []
        self.dependencies = {}
        self.populateAdditions(sel)
        self.populateDependencies(sel)
        self.gui = obj.ViewObject
        self.attr = {attr : getattr(self.gui, attr) for attr in hideAttribute}
        self.ghost = {}
        ## Dependencies' ghosts will not be in foreground
        if self.isDependency:
            self.populateGhost()
        ## Populate caller selection list
        if self not in sel:
            sel.append(self)

    def get_attr(self, name, attr):
        ''' Catch properties which are used in expressions of its InList '''
        return re.search(name + '\.(.*?)(\s|$)', attr).group(1)

    def hide(self):
        ''' Hide the real object in order to not disturb the 
        (transparent) ghost visibility.
        Dependencies' ghosts overlay real objects: so there is no need to
        hide or show the real objects '''
        if not self.isDependency:
            for attr in hideAttribute:
                setattr(self.gui, attr, hideAttribute[attr])
    
    def show(self):
        ''' Show the real object (usually used when ghost is off).
        Dependencies' ghosts overlay real objects: so there is no need to
        hide or show the real objects '''
        if not self.isDependency:
            for attr in hideAttribute:
                setattr(self.gui, attr, self.attr[attr])

    def setBase(self, obj, sel):
        ''' Create a SelectedObject for the base of the object.
         If is a base yet, create a new one and set its parent to None 
         to avoid infinite recursive call '''

        if 'Base' in self.obj.PropertiesList and obj.Base:
            return SelectedObject(obj.Base, sel, self.selectionType + '_base', 
                    self)
        elif 'base' not in self.selectionType:
            return SelectedObject(obj, sel, self.selectionType + '_base', None)
        else:
            return None

    def populateDependencies(self, sel):
        for dep in self.obj.InList:
            for pair in dep.ExpressionEngine:
                ## if object is used in expression
                ## (TODO: check in case of objects with same name ends)
                if self.name + '.' in pair[1]:
                    local_attr = self.get_attr(self.name, pair[1])
                    if local_attr not in self.dependencies:
                        self.dependencies[local_attr] = []
                    ## Create a new SelectedObject for every dependency
                    self.dependencies[local_attr].append((SelectedObject(dep,
                        sel, self.selectionType + '_dependency'), pair[0]))

    def populateAdditions(self, sel, obj=None):
        ''' Recursive function to create a SelectedObject for every additions 
        (and eventually for the additions of additions)'''
        if not obj:
            obj = self.obj
        if 'Additions' in obj.PropertiesList and len(obj.Additions) > 0:
            for o in obj.Additions:
                if (o, 'addition') not in [(s.obj, s.selectionType) \
                        for s in sel]:
                    ## Create a new SelectedObject of type "addition" if obj 
                    ## is not present in the selection list as "addition"
                    self.additions.append(SelectedObject(o, sel, 'addition'))
                    self.populateAdditions(sel, o)
                else:
                    for s in sel:
                        if s.obj == o and s.selectionType == 'addition':
                            ## If already in selection list as "addition" put it
                            ## in the list without creating a new SelectedObject
                            self.additions.append(s)
                            break

    def populateGhost(self):
        ''' Create a ghost for every selection condition '''
        FreeCADGui.Selection.clearSelection()
        ob = self.obj
        visible = ob.ViewObject.Visibility
        tempAdds = []
        if not visible:
            ## Object need to be visible in order to create the ghost
            ob.ViewObject.Visibility = True
        if 'Additions' in ob.PropertiesList and len(ob.Additions) > 0:
            ## Remove all the additions and take note of them: 
            ## need to restore them later
            tempAdds = ob.Additions
            ob.Additions = []
            FreeCAD.ActiveDocument.recompute()
        for typ in ['normal', 'toEdit', 'dirDeps', 'exprDeps']:
            ## Create a multighost for every selection condition
            separator = self.obj.ViewObject.RootNode.copy()
            self.ghost.update({typ: multiGhostTracker(
                self.obj, separator, typ)})
        ## Restore additions and visibility
        if len(tempAdds) > 0:
            ob.Additions += tempAdds
        if not visible:
            ob.ViewObject.Visibility = False


class BaseTransform(Modifier):
    "The BaseTransform command definition"

    def __init__(self):
        Modifier.__init__(self)
        self.keys = {
                'g': lambda x: bimMove(x),
                'r': lambda x: bimRotate(x),
                #'s': lambda x: bimScale(x),
                #'m': lambda x: bimMirror(x),
                #'t': lambda x: bimStretch(x),
                }
        self.call_sel = None
        self.call_key = None
        self.call_status = None
        self.selection = []
        self.sel_options = sorted(selectionOption().keys())
        self.sel_opt_no = 0

    def Activated(self):
        self.name = translate("draft","BaseTransform", utf8_decode=True)
        Modifier.Activated(self,self.name)
        if self.ui:
            if not FreeCADGui.Selection.getSelection():
                self.ui.selectUi()
                msg(translate("draft", "Select an object to edit")+"\n")
                self.call_sel = \
                        self.view.addEventCallback("SoEvent", selectObject)
                ## TODO it should allow multiple selections
                ## TODO Ui should be more explanatory
            else:
                self.proceed()

    def proceed(self):
        if self.call_sel:
            self.view.removeEventCallback("SoEvent",self.call_sel)
        self.sel = FreeCADGui.Selection.getSelection()
        self.sel = Draft.getGroupContents(self.sel,addgroups=True,spaces=True,
                noarchchild=True)

        ## self.actual_selection is what the user clicked
        ## self.selection is the actual selection extended to bases, 
        ## additions and dependencies
        self.actual_selection = [SelectedObject(o, self.selection) \
                for o in self.sel]
        ## Create the ghosts for selection: 
        ## 2d object are done on last to keep them in foreground
        for o in self.selection:
            if 'Part2DObject' not in o.obj.TypeId and not o.isDependency :
                o.populateGhost()
        for o in self.selection:
            if 'Part2DObject' in o.obj.TypeId and not o.isDependency:
                o.populateGhost()
        FreeCADGui.Selection.clearSelection()

        self.getSelectionSet()
        self.call_key = self.view.addEventCallback(
            "SoKeyboardEvent", self.key_switch)

    def getSelectionSet(self):
        ''' Get the selection set based on available options
        (see selectionOption())'''
        for so in self.selection:
            for gt in so.ghost:
                if so.ghost[gt].switch:
                    so.ghost[gt].off()
        no  = self.sel_opt_no
        self.sel_opt_no = (self.sel_opt_no + 1) % len(self.sel_options)
        self.possible_selections = selectionOption(self.selection)
        temp_sel = self.possible_selections[self.sel_options[no]]
        FreeCAD.Console.PrintMessage('\n' + temp_sel['print'] + '\n')
        self.chosen_selection = {k: temp_sel[k] for k in temp_sel if k != 'print'}
        #print(self.chosen_selection)
        for outer, st in enumerate(self.chosen_selection):
            for inner, so in enumerate(self.chosen_selection[st]):
                ## Hide objects, show ghosts
                so.hide()
                so.ghost[st].on()

    def key_switch(self,info):
        ''' According to the key pressed do:
        - Ctrl + Space -> Switch selection type
        - q -> Restore visibility and quit the command
        - g or r or ... -> Launch the tranformation '''

        if info['Type'] == 'SoKeyboardEvent' and info['Key'] == 'SPACE' \
                and info['State'] == 'UP' and info['CtrlDown'] == True:
                    print(info['Key'], 'pressed!')
                    self.getSelectionSet()
        elif info['Type'] == 'SoKeyboardEvent' and info['Key'] == 'q' \
                and info['State'] == 'UP':
                    print(info['Key'], 'pressed!')
                    self.stopHightlight()
        elif info['Type'] == 'SoKeyboardEvent' and info['Key'] in self.keys \
                and info['State'] == 'UP':
                    print(info['Key'], 'pressed!')
                    self.getTransform(info['Key'])

    def stopHightlight(self):
        ''' Delete ghosts, restore visibility of objects and 
        quit the command '''
        FreeCADGui.Selection.clearSelection()
        for so in self.selection:
            for gt in so.ghost:
                if so.ghost[gt].switch:
                    so.ghost[gt].off()
            so.show()
            FreeCAD.ActiveDocument.recompute()
        self.view.removeEventCallback("SoKeyboardEvent", self.call_key)

    def getTransform(self, key):
        ''' Create the transformation and activate it '''

        self.view.removeEventCallback("SoKeyboardEvent", self.call_key)
        #print(self.chosen_selection)
        self.transform = self.keys[key](self.chosen_selection)
        self.transform.Activated()
        self.call_status = self.view.addEventCallback("SoEvent", self.status)

    def status(self, info):
        ''' Close the command when the transofrmation is over '''

        if not FreeCAD.activeDraftCommand:
            ## Transformation completed
            self.view.removeEventCallback("SoEvent", self.call_status)
            print('finished')
            FreeCADGui.Selection.clearSelection()
            for so in self.selection:
                ## Delete ghosts and restore visibility of objects
                so.ghost = {}
                so.show()
            FreeCAD.activeDocument().recompute()

    def finish(self):
        ## TODO Make sure it finishes when push "Close" or escape
        FreeCAD.activeDocument().recompute()
        self.call_sel = None
        self.call_key = None
        self.call_status = None
        Modifier.finish(self)


bt = BaseTransform()
bt.Activated()
