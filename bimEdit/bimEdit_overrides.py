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

import FreeCAD, FreeCADGui, Draft, math, DraftGui
from DraftGui import todo, translate, utf8_decode
from FreeCAD import Vector
from DraftTools import Modifier, msg, selectObject, plane, \
        getPoint, redraw3DView, hasMod, MODALT, DraftVecUtils, \
        Move, Rotate
from DraftTrackers import ghostTracker, arcTracker


def replica(to_edit):
    ''' Create a replica, even maintaining relations between additions, 
    and return it in a list of new object to copy ''' 
    from bimEdit import hideAttribute
    to_copy = []
    copy_adds = {}
    for sel in to_edit:
        new_obj = FreeCAD.ActiveDocument.copyObject(sel.obj)
        adds = sel.obj.Additions if 'Additions' in sel.obj.PropertiesList \
                else None
        if adds and len(adds) > 0:
            new_obj.Additions = []
        for attr in hideAttribute:
            setattr(new_obj.ViewObject, attr, sel.attr[attr])
        copy_adds.update({
            sel.obj: {'copy':new_obj, 'additions': adds}})
        to_copy.append(new_obj)
        if sel.parent:
            new_parent = FreeCAD.ActiveDocument.copyObject(sel.parent.obj)
            if 'Additions' in new_parent.PropertiesList \
                    and len(new_parent.Additions) > 0:
                new_parent.Additions = []
            copy_adds.update({
                sel.parent.obj: {'copy':new_parent, 
                    'additions': sel.parent.obj.Additions}})
            new_parent.Base = new_obj
            for attr in hideAttribute:
                setattr(new_parent.ViewObject, attr, sel.parent.attr[attr])
    #print({c.Name: copy_adds[c] for c in copy_adds})
    for o in copy_adds:
        if copy_adds[o]['additions']:
            copy_adds[o]['copy'].Additions = [copy_adds[a]['copy'] \
                    for a in copy_adds[o]['additions'] if a in copy_adds]
    return to_copy


class bimMove(Move):
    "The bimMove command definition"

    def __init__(self, sel_dict):
        super().__init__()
        self.sel_dict = sel_dict

    def Activated(self):
        from bimEdit import hideAttribute
        self.name = translate("draft","bimMove", utf8_decode=True)
        Modifier.Activated(self,self.name)
        self.ghost = {}
        for typ in self.sel_dict:
            if typ not in self.ghost:
                self.ghost.update({typ:[]})
            for o in self.sel_dict[typ]:
                self.ghost[typ].append(o.ghost[typ])

        ## Proceeding
        if self.call:
            self.view.removeEventCallback("SoEvent",self.call)
        self.ui.pointUi(self.name)
        self.ui.modUi()
        if self.copymode:
            self.ui.isCopy.setChecked(True)
        self.ui.xValue.setFocus()
        self.ui.xValue.selectAll()

        self.call = self.view.addEventCallback("SoEvent",self.action)
        msg(translate("draft", "Pick start point:")+"\n")

    def finish(self,closed=False,cont=False):
        if self.ghost:
            for typ in self.ghost:
                for g in [i for i in self.ghost[typ]]:
                    if g.switch:
                        g.off()
                    g.finalize()
        if cont and self.ui:
            if self.ui.continueMode:
                todo.delayAfter(self.Activated,[])
        Modifier.finish(self)

    def move(self,delta,copy=False):
        "moving the real shape's bases"
        FreeCADGui.addModule("Draft")
        sel_to_edit = [o for typ in self.sel_dict \
                for o in self.sel_dict[typ] if typ == 'toEdit']
        if copy:
            obj_to_edit = replica(sel_to_edit)
        else:
            obj_to_edit = [s.obj for s in sel_to_edit]

        sel = '['
        for o in obj_to_edit:
            if len(sel) > 1:
                sel += ','
            sel += 'FreeCAD.ActiveDocument.' + o.Name
        sel += ']'

        self.commit(translate("draft","Move"),
            ['Draft.move('+sel+','+DraftVecUtils.toString(delta)+ \
                ',copy=False)', 'FreeCAD.ActiveDocument.recompute()'])

    def action(self,arg):
        "scene event handler"
        if arg["Type"] == "SoKeyboardEvent":
            if arg["Key"] == "ESCAPE":
                self.finish()
        elif arg["Type"] == "SoLocation2Event": #mouse movement detection
            #if self.ghost:
            #    self.ghost.off()
            self.point,ctrlPoint,info = getPoint(self,arg)
            if (len(self.node) > 0):
                last = self.node[len(self.node)-1]
                delta = self.point.sub(last)
                if self.ghost:
                    for typ in self.ghost:
                        if typ == 'toEdit' or typ == 'dirDeps':
                            for g in [i for i in self.ghost[typ]]:
                                g.move(delta)
                                g.on()
            if self.extendedCopy:
                if not hasMod(arg,MODALT): self.finish()
            redraw3DView()
        elif arg["Type"] == "SoMouseButtonEvent":
            if (arg["State"] == "DOWN") and (arg["Button"] == "BUTTON1"):
                if self.point:
                    self.ui.redraw()
                    if (self.node == []):
                        self.node.append(self.point)
                        self.ui.isRelative.show()
                        if self.ghost:
                            for typ in self.ghost:
                                if typ == 'toEdit' or typ == 'dirDeps':
                                    for g in [i for i in self.ghost[typ]]:
                                        g.on()
                        msg(translate("draft", "Pick end point:")+"\n")
                        if self.planetrack:
                            self.planetrack.set(self.point)
                    else:
                        last = self.node[0]
                        if self.ui.isCopy.isChecked() or hasMod(arg,MODALT):
                            self.move(self.point.sub(last),True)
                        else:
                            self.move(self.point.sub(last))
                        if hasMod(arg,MODALT):
                            self.extendedCopy = True
                        else:
                            self.finish(cont=True)

    def numericInput(self,numx,numy,numz):
        "this function gets called by the toolbar when valid x, y, and z \
                have been entered there"
        self.point = Vector(numx,numy,numz)
        if not self.node:
            self.node.append(self.point)
            self.ui.isRelative.show()
            self.ui.isCopy.show()
            for typ in self.ghost:
                if typ == 'toEdit' or typ == 'dirDeps':
                    for g in [i for i in self.ghost[typ]]:
                        g.on()
            msg(translate("draft", "Pick end point:")+"\n")
        else:
            last = self.node[-1]
            if self.ui.isCopy.isChecked():
                self.move(self.point.sub(last),True)
            else:
                self.move(self.point.sub(last))
            self.finish()


class bimRotate(Rotate):
    "The bimMove command definition"

    def __init__(self, sel_dict):
        super().__init__()
        self.sel_dict = sel_dict

    def Activated(self):
        from bimEdit import hideAttribute
        self.name = translate("draft","bimRotate", utf8_decode=True)
        Modifier.Activated(self,self.name)
        self.ghost = {}
        for typ in self.sel_dict:
            if typ not in self.ghost:
                self.ghost.update({typ:[]})
            for o in self.sel_dict[typ]:
                self.ghost[typ].append(o.ghost[typ])
        self.arctrack = None

        ## Proceeding
        if self.call:
            self.view.removeEventCallback("SoEvent",self.call)
        self.step = 0
        self.center = None
        self.ui.arcUi()
        self.ui.modUi()
        self.ui.setTitle("Rotate")
        self.arctrack = arcTracker()
        self.call = self.view.addEventCallback("SoEvent",self.action)

        msg(translate("draft", "Pick rotation center:")+"\n")

    def finish(self,closed=False,cont=False):
        "finishes the arc"
        if self.arctrack:
            self.arctrack.finalize()
        if self.ghost:
            for typ in self.ghost:
                for g in [i for i in self.ghost[typ]]:
                    if g.switch:
                        g.off()
                    g.finalize()
        if cont and self.ui:
            if self.ui.continueMode:
                todo.delayAfter(self.Activated,[])
        Modifier.finish(self)
        if self.doc:
            self.doc.recompute()

    def rot (self,angle,copy=False):
        "rotating the real shapes'bases"
        FreeCADGui.addModule("Draft")
        sel_to_edit = [o for typ in self.sel_dict \
                for o in self.sel_dict[typ] if typ == 'toEdit']
        if copy:
            obj_to_edit = replica(sel_to_edit)
        else:
            obj_to_edit = [s.obj for s in sel_to_edit]

        sel = '['
        for o in obj_to_edit:
            if len(sel) > 1:
                sel += ','
            sel += 'FreeCAD.ActiveDocument.'+o.Name
        sel += ']'
            
        self.commit(translate("draft","Rotate"),
            ['Draft.rotate('+sel+','+str(math.degrees(angle))+','+ \
                    DraftVecUtils.toString(self.center)+',axis='+ \
                    DraftVecUtils.toString(plane.axis)+',copy=False)'])

        ## TODO define behaviour for rotation around non-z axis
        #for ob in obj_to_edit:
        #    if ob.Proxy.__module__ == 'ArchWall':
        #        normal = normalizeNormal(ob) 
        #        rotatedNormal = DraftVecUtils.rotate(normal,angle,plane.axis)
        #        print(rotatedNormal)
        #        ob.Normal = rotatedNormal
        #        print(ob.Normal)
        #        App.activeDocument().recompute()

    def action(self,arg):
        "scene event handler"
        if arg["Type"] == "SoKeyboardEvent":
            if arg["Key"] == "ESCAPE":
                self.finish()
        elif arg["Type"] == "SoLocation2Event":
            #if self.ghost:
            #    self.ghost.off()
            self.point,ctrlPoint,info = getPoint(self,arg)
            # this is to make sure radius is what you see on screen
            if self.center and DraftVecUtils.dist(self.point,self.center):
                viewdelta = DraftVecUtils.project(self.point.sub(self.center),
                        plane.axis)
                if not DraftVecUtils.isNull(viewdelta):
                    self.point = self.point.add(viewdelta.negative())
            if self.extendedCopy:
                if not hasMod(arg,MODALT):
                    self.step = 3
                    self.finish()
            if (self.step == 0):
                pass
            elif (self.step == 1):
                currentrad = DraftVecUtils.dist(self.point,self.center)
                if (currentrad != 0):
                    angle = DraftVecUtils.angle(plane.u,
                            self.point.sub(self.center), plane.axis)
                else: angle = 0
                self.ui.setRadiusValue(math.degrees(angle),unit="Angle")
                self.firstangle = angle
                self.ui.radiusValue.setFocus()
                self.ui.radiusValue.selectAll()
            elif (self.step == 2):
                currentrad = DraftVecUtils.dist(self.point,self.center)
                if (currentrad != 0):
                    angle = DraftVecUtils.angle(plane.u, 
                            self.point.sub(self.center), plane.axis)
                else: angle = 0
                if (angle < self.firstangle):
                    sweep = (2*math.pi-self.firstangle)+angle
                else:
                    sweep = angle - self.firstangle
                self.arctrack.setApertureAngle(sweep)
                if self.ghost:
                    for typ in self.ghost:
                        if typ == 'toEdit' or typ == 'dirDeps':
                            for g in [i for i in self.ghost[typ]]:
                                g.rotate(plane.axis,sweep)
                                g.on()
                self.ui.setRadiusValue(math.degrees(sweep), 'Angle')
                self.ui.radiusValue.setFocus()
                self.ui.radiusValue.selectAll()
            redraw3DView()

        elif arg["Type"] == "SoMouseButtonEvent":
            if (arg["State"] == "DOWN") and (arg["Button"] == "BUTTON1"):
                if self.point:
                    if (self.step == 0):
                        self.center = self.point
                        self.node = [self.point]
                        self.ui.radiusUi()
                        self.ui.radiusValue.setText(FreeCAD.Units.Quantity(
                            0,FreeCAD.Units.Angle).UserString)
                        self.ui.hasFill.hide()
                        self.ui.labelRadius.setText("Base angle")
                        self.arctrack.setCenter(self.center)
                        if self.ghost:
                            for typ in self.ghost:
                                if typ == 'toEdit' or typ == 'dirDeps':
                                    for g in [i for i in self.ghost[typ]]:
                                        g.center(self.center)
                        self.step = 1
                        msg(translate("draft", "Pick base angle:")+"\n")
                        if self.planetrack:
                            self.planetrack.set(self.point)
                    elif (self.step == 1):
                        self.ui.labelRadius.setText("Rotation")
                        self.rad = DraftVecUtils.dist(self.point,self.center)
                        self.arctrack.on()
                        self.arctrack.setStartPoint(self.point)
                        if self.ghost:
                            for typ in self.ghost:
                                if typ == 'toEdit' or typ == 'dirDeps':
                                    for g in [i for i in self.ghost[typ]]:
                                        g.on()
                        self.step = 2
                        msg(translate("draft", "Pick rotation angle:")+"\n")
                    else:
                        currentrad = DraftVecUtils.dist(self.point,self.center)
                        angle = self.point.sub(self.center).getAngle(plane.u)
                        if DraftVecUtils.project(self.point.sub(self.center), 
                                plane.v).getAngle(plane.v) > 1:
                            angle = -angle
                        if (angle < self.firstangle):
                            sweep = (2*math.pi-self.firstangle)+angle
                        else:
                            sweep = angle - self.firstangle
                        if self.ui.isCopy.isChecked() or hasMod(arg,MODALT):
                            self.rot(sweep,True)
                        else:
                            self.rot(sweep)
                        if hasMod(arg,MODALT):
                            self.extendedCopy = True
                        else:
                            self.finish(cont=True)

    def numericInput(self,numx,numy,numz):
        "this function gets called by the toolbar when valid x, y, and z \
                have been entered there"
        self.center = Vector(numx,numy,numz)
        self.node = [self.center]
        self.arctrack.setCenter(self.center)
        if self.ghost:
            for typ in self.ghost:
                if typ == 'toEdit' or typ == 'dirDeps':
                    for g in [i for i in self.ghost[typ]]:
                        g.center(self.center)
        self.ui.radiusUi()
        self.ui.hasFill.hide()
        self.ui.labelRadius.setText("Base angle")
        self.step = 1
        msg(translate("draft", "Pick base angle:")+"\n")

    def numericRadius(self,rad):
        "this function gets called by the toolbar when valid radius have been entered there"
        if (self.step == 1):
            self.ui.labelRadius.setText("Rotation")
            self.firstangle = math.radians(rad)
            self.arctrack.setStartAngle(self.firstangle)
            self.arctrack.on()
            if self.ghost:
                for typ in self.ghost:
                    if typ == 'toEdit' or typ == 'dirDeps':
                        for g in [i for i in self.ghost[typ]]:
                            g.on()
            self.step = 2
            msg(translate("draft", "Pick rotation angle:")+"\n")
        else:
            self.rot(math.radians(rad),self.ui.isCopy.isChecked())
            self.finish(cont=True)


class bimScale(Modifier):
    '''The Draft_Scale FreeCAD command definition.
    This tool scales the selected objects from a base point.'''

    def GetResources(self):
        return {'Pixmap'  : 'Draft_Scale',
                'Accel' : "S, C",
                'MenuText': QtCore.QT_TRANSLATE_NOOP("Draft_Scale", "Scale"),
                'ToolTip': QtCore.QT_TRANSLATE_NOOP("Draft_Scale", "Scales the selected objects from a base point. CTRL to snap, SHIFT to constrain, ALT to copy")}

    def Activated(self):
        self.name = translate("draft","Scale", utf8_decode=True)
        Modifier.Activated(self,self.name)
        self.ghost = None
        if self.ui:
            if not FreeCADGui.Selection.getSelection():
                self.ui.selectUi()
                msg(translate("draft", "Select an object to scale")+"\n")
                self.call = self.view.addEventCallback("SoEvent",selectObject)
            else:
                self.proceed()

    def proceed(self):
        if self.call: self.view.removeEventCallback("SoEvent",self.call)
        self.sel = FreeCADGui.Selection.getSelection()
        self.sel = Draft.getGroupContents(self.sel)
        self.refs = []
        self.ui.pointUi(self.name)
        self.ui.modUi()
        self.ui.xValue.setFocus()
        self.ui.xValue.selectAll()
        self.ghost = ghostTracker(self.sel)
        self.pickmode = False
        self.task = None
        self.call = self.view.addEventCallback("SoEvent",self.action)
        msg(translate("draft", "Pick base point:")+"\n")

    def pickRef(self):
        self.pickmode = True
        if self.node:
            self.node = self.node[:1] # remove previous picks
        msg(translate("draft", "Pick reference distance from base point:")+"\n")
        self.call = self.view.addEventCallback("SoEvent",self.action)

    def finish(self,closed=False,cont=False):
        Modifier.finish(self)
        if self.ghost:
            self.ghost.finalize()

    def scale(self,x,y,z,rel,mode):
        delta = Vector(x,y,z)
        if rel:
            delta = FreeCAD.DraftWorkingPlane.getGlobalCoords(delta)
        if mode == 0:
            copy = False
            legacy = False
        elif mode == 1:
            copy = False
            legacy = True
        elif mode == 2:
            copy = True
            legacy = True
        "moving the real shapes"
        sel = '['
        for o in self.sel:
            if len(sel) > 1:
                sel += ','
            sel += 'FreeCAD.ActiveDocument.'+o.Name
        sel += ']'
        FreeCADGui.addModule("Draft")
        self.commit(translate("draft","Copy"),
                    ['Draft.scale('+sel+',delta='+DraftVecUtils.toString(delta)+',center='+DraftVecUtils.toString(self.node[0])+',copy='+str(copy)+',legacy='+str(legacy)+')',
                     'FreeCAD.ActiveDocument.recompute()'])
        self.finish()

    def scaleGhost(self,x,y,z,rel):
        delta = Vector(x,y,z)
        if rel:
            delta = FreeCAD.DraftWorkingPlane.getGlobalCoords(delta)
        self.ghost.scale(delta)
        # calculate a correction factor depending on the scaling center
        corr = Vector(self.node[0].x,self.node[0].y,self.node[0].z)
        corr.scale(delta.x,delta.y,delta.z)
        corr = (corr.sub(self.node[0])).negative()
        self.ghost.move(corr)
        self.ghost.on()

    def action(self,arg):
        "scene event handler"
        if arg["Type"] == "SoKeyboardEvent":
            if arg["Key"] == "ESCAPE":
                self.finish()
        elif arg["Type"] == "SoLocation2Event": #mouse movement detection
            if self.ghost:
                self.ghost.off()
            self.point,ctrlPoint,info = getPoint(self,arg,sym=True)
        elif arg["Type"] == "SoMouseButtonEvent":
            if (arg["State"] == "DOWN") and (arg["Button"] == "BUTTON1"):
                if self.point:
                    #self.ui.redraw()
                    self.numericInput(self.point.x,self.point.y,self.point.z)

    def numericInput(self,numx,numy,numz):
        "this function gets called by the toolbar when a valid base point has been entered"
        self.point = Vector(numx,numy,numz)
        self.node.append(self.point)
        if not self.pickmode:
            self.ui.offUi()
            if self.call:
                self.view.removeEventCallback("SoEvent",self.call)
            self.task = DraftGui.ScaleTaskPanel()
            self.task.sourceCmd = self
            DraftGui.todo.delay(FreeCADGui.Control.showDialog,self.task)
            if self.ghost:
                self.ghost.on()
        elif len(self.node) == 2:
            msg(translate("draft", "Pick new distance from base point:")+"\n")
        elif len(self.node) == 3:
            if hasattr(FreeCADGui,"Snapper"):
                FreeCADGui.Snapper.off()
            if self.call:
                self.view.removeEventCallback("SoEvent",self.call)
            d1 = (self.node[1].sub(self.node[0])).Length
            d2 = (self.node[2].sub(self.node[0])).Length
            #print d2,"/",d1,"=",d2/d1
            if hasattr(self,"task"):
                if self.task:
                    self.task.lock.setChecked(True)
                    self.task.setValue(d2/d1)



def scale(objectslist,delta=Vector(1,1,1),center=Vector(0,0,0),copy=False,legacy=False):
    '''scale(objects,vector,[center,copy,legacy]): Scales the objects contained
    in objects (that can be a list of objects or an object) of the given scale
    factors defined by the given vector (in X, Y and Z directions) around
    given center. If legacy is True, direct (old) mode is used, otherwise
    a parametric copy is made. If copy is True, the actual objects are not moved,
    but copies are created instead. The objects (or their copies) are returned.'''
    if not isinstance(objectslist,list): objectslist = [objectslist]
    if legacy:
        newobjlist = []
        for obj in objectslist:
            if copy:
                newobj = makeCopy(obj)
            else:
                newobj = obj
            if obj.isDerivedFrom("Part::Feature"):
                sh = obj.Shape.copy()
                m = FreeCAD.Matrix()
                m.scale(delta)
                sh = sh.transformGeometry(m)
                corr = Vector(center.x,center.y,center.z)
                corr.scale(delta.x,delta.y,delta.z)
                corr = (corr.sub(center)).negative()
                sh.translate(corr)
            if getType(obj) == "Rectangle":
                p = []
                for v in sh.Vertexes: p.append(v.Point)
                pl = obj.Placement.copy()
                pl.Base = p[0]
                diag = p[2].sub(p[0])
                bb = p[1].sub(p[0])
                bh = p[3].sub(p[0])
                nb = DraftVecUtils.project(diag,bb)
                nh = DraftVecUtils.project(diag,bh)
                if obj.Length < 0: l = -nb.Length
                else: l = nb.Length
                if obj.Height < 0: h = -nh.Length
                else: h = nh.Length
                newobj.Length = l
                newobj.Height = h
                tr = p[0].sub(obj.Shape.Vertexes[0].Point)
                newobj.Placement = pl
            elif getType(obj) == "Wire":
                p = []
                for v in sh.Vertexes: p.append(v.Point)
                #print(p)
                newobj.Points = p
            elif getType(obj) == "BSpline":
                p = []
                for p1 in obj.Points:
                    p2 = p1.sub(center)
                    p2.scale(delta.x,delta.y,delta.z)
                    p.append(p2)
                newobj.Points = p
            elif (obj.isDerivedFrom("Part::Feature")):
                newobj.Shape = sh
            elif (obj.TypeId == "App::Annotation"):
                factor = delta.y * obj.ViewObject.FontSize
                newobj.ViewObject.FontSize = factor
                d = obj.Position.sub(center)
                newobj.Position = center.add(Vector(d.x*delta.x,d.y*delta.y,d.z*delta.z))
            if copy:
                formatObject(newobj,obj)
            newobjlist.append(newobj)
        if copy and getParam("selectBaseObjects",False):
            select(objectslist)
        else:
            select(newobjlist)
        if len(newobjlist) == 1: return newobjlist[0]
        return newobjlist
    else:
        obj = FreeCAD.ActiveDocument.addObject("Part::FeaturePython","Scale")
        _Clone(obj)
        obj.Objects = objectslist
        obj.Scale = delta
        corr = Vector(center.x,center.y,center.z)
        corr.scale(delta.x,delta.y,delta.z)
        corr = (corr.sub(center)).negative()
        p = obj.Placement
        p.move(corr)
        obj.Placement = p
        if not copy:
            for o in objectslist:
                o.ViewObject.hide()
        if gui:
            _ViewProviderClone(obj.ViewObject)
            formatObject(obj,objectslist[-1])
            select(obj)
        return obj

