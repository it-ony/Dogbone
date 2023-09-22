import os
from typing import cast

import adsk.core
import adsk.fusion
from .util import calcId
from .DbData import DbParams
from .DbClasses import DbFace

from .decorators import eventHandler, parseDecorator

FROM_TOP_FACE = "From Top Face"
FROM_SELECTED_FACE = "From Selected Face"
ON_SHORT_SIDE = "On Short Side"
ON_LONG_SIDE = "On Long Side"
NORMAL_DOGBONE = "Normal Dogbone"
MODE_GROUP = "modeGroup"
PARAMETRIC = "Parametric"
STATIC = "Static"
ANGLE_DETECTION_GROUP = "angleDetectionGroup"
MODE_ROW = "modeRow"
OBTUSE_ANGLE = "obtuseAngle"
ACUTE_ANGLE = "acuteAngle"
MAX_SLIDER = "maxSlider"
MIN_SLIDER = "minSlider"
MORTISE_DOGBONE = "Mortise Dogbone"
MINIMAL_DOGBONE = "Minimal Dogbone"
LOGGING = "logging"
BENCHMARK = "benchmark"
SETTINGS_GROUP = "settingsGroup"
DEPTH_EXTENT = "depthExtent"
MINIMAL_PERCENT = "minimalPercent"
MORTISE_TYPE = "mortiseType"
DOGBONE_TYPE = "dogboneType"
TOOL_DIAMETER = "toolDia"
EDGE_SELECT = "edgeSelect"
FACE_SELECT = "faceSelect"
TOOL_DIAMETER_OFFSET = "toolDiaOffset"

_appPath = os.path.dirname(os.path.abspath(__file__))
_app = adsk.core.Application.get()
_design: adsk.fusion.Design = cast(adsk.fusion.Design, _app.activeProduct)
_ui = _app.userInterface


# noinspection SqlDialectInspection,SqlNoDataSourceInspection,PyMethodMayBeStatic
class DogboneUi:

    def __init__(self, params: DbParams, command: adsk.core.Command, logger) -> None:
        super().__init__()

        self.param = params
        self.command = command
        self.logger = logger

        self.inputs = command.commandInputs

        self.selectedOccurrences = {}  # key hash(occurrence.entityToken) value:[DbFace,...]
        self.selectedFaces = {}  # key: hash(face.entityToken) value:[DbFace,...]
        self.selectedEdges = {}  # kay: hash(edge.entityToken) value:[DbEdge, ...]

        self.create_ui()
        self.onInputChanged(event=command.inputChanged)

    def create_ui(self):
        self.face_select()
        self.edge_select()
        self.tool_diameter()
        self.offset()
        self.mode()
        self.detection_mode()
        self.settings()

    @eventHandler(handler_cls=adsk.core.InputChangedEventHandler)
    @parseDecorator
    def onInputChanged(self, args: adsk.core.InputChangedEventArgs):
        input: adsk.core.CommandInput = args.input
        self.logger.debug(f"input changed- {input.id}")

        # TODO: instead of finding the elements again via id, better to take the reference. Then the casting is
        # not necessary anymore and the code becomes way slimmer

        if input.id == DOGBONE_TYPE:
            input.commandInputs.itemById(MINIMAL_PERCENT).isVisible = (
                    cast(adsk.core.ButtonRowCommandInput, input.commandInputs.itemById(DOGBONE_TYPE)).selectedItem.name
                    == MINIMAL_DOGBONE
            )
            input.commandInputs.itemById(MORTISE_TYPE).isVisible = (
                    cast(adsk.core.ButtonRowCommandInput, input.commandInputs.itemById(DOGBONE_TYPE)).selectedItem.name
                    == MORTISE_DOGBONE
            )
            return

        if input.id == "toolDia":
            self.param.toolDiaStr = cast(adsk.core.ValueCommandInput, input).expression
            return

        if input.id == MODE_ROW:
            input.parentCommand.commandInputs.itemById(
                ANGLE_DETECTION_GROUP
            ).isVisible = (cast(adsk.core.ButtonRowCommandInput, input).selectedItem.name == STATIC)
            self.param.parametric = cast(adsk.core.ButtonRowCommandInput, input).selectedItem.name == PARAMETRIC  #

        if input.id == ACUTE_ANGLE:
            b = cast(adsk.core.BoolValueCommandInput, input)
            input.commandInputs.itemById(
                MIN_SLIDER
            ).isVisible = b.value
            self.param.acuteAngle = b.value

        if input.id == MIN_SLIDER:
            self.param.minAngleLimit = cast(adsk.core.FloatSliderCommandInput, input.commandInputs.itemById(
                MIN_SLIDER
            )).valueOne

        if input.id == OBTUSE_ANGLE:
            b = cast(adsk.core.BoolValueCommandInput, input)
            input.commandInputs.itemById(
                MAX_SLIDER
            ).isVisible = b.value
            self.param.obtuseAngle = b.value

        if input.id == MAX_SLIDER:
            self.param.maxAngleLimit = cast(adsk.core.FloatSliderCommandInput, input.commandInputs.itemById(
                MAX_SLIDER
            )).valueOne

        #
        if (
                input.id == ACUTE_ANGLE
                or input.id == OBTUSE_ANGLE
                or input.id == MIN_SLIDER
                or input.id == MAX_SLIDER
                or input.id == MODE_ROW
        ):  # refresh edges after specific input changes
            edgeSelectCommand = input.parentCommand.commandInputs.itemById(
                EDGE_SELECT
            )
            if not edgeSelectCommand.isVisible:
                return
            focusState = cast(adsk.core.SelectionCommandInput, input.parentCommand.commandInputs.itemById(
                FACE_SELECT
            )).hasFocus
            edgeSelectCommand.hasFocus = True
            [
                _ui.activeSelections.removeByEntity(edgeObj.edge)
                for edgeObj in self.selectedEdges.values()
            ]
            [faceObj.reSelectEdges() for faceObj in self.selectedFaces.values()]
            input.parentCommand.commandInputs.itemById(
                FACE_SELECT
            ).hasFocus = focusState
            return

        if input.id != FACE_SELECT and input.id != EDGE_SELECT:
            return

        self.logger.debug(f"input changed- {input.id}")
        s = cast(adsk.core.SelectionCommandInput, input)
        if input.id == FACE_SELECT:
            # ==============================================================================
            #            processing changes to face selections
            # ==============================================================================

            if len(self.selectedFaces) > s.selectionCount:
                # a face has been removed

                # If all faces are removed, just reset registers
                if s.selectionCount == 0:
                    self.selectedEdges = {}
                    self.selectedFaces = {}
                    self.selectedOccurrences = {}

                    cast(adsk.core.SelectionCommandInput, input.commandInputs.itemById(EDGE_SELECT)).clearSelection()
                    input.commandInputs.itemById(FACE_SELECT).hasFocus = True
                    input.commandInputs.itemById(EDGE_SELECT).isVisible = False
                    return

                # Else find the missing face in selection
                selectionSet = {
                    hash(s.selection(i).entity.entityToken)
                    for i in range(s.selectionCount)
                }
                missingFaces = set(self.selectedFaces.keys()) ^ selectionSet
                input.commandInputs.itemById(EDGE_SELECT).isVisible = True
                input.commandInputs.itemById(EDGE_SELECT).hasFocus = True
                [
                    (
                        self.selectedFaces[
                            missingFace
                        ].removeFaceFromSelectedOccurrences(),
                        self.selectedFaces[missingFace].deleteEdges(),
                        self.selectedFaces.pop(missingFace),
                    )
                    for missingFace in missingFaces
                ]
                input.commandInputs.itemById(FACE_SELECT).hasFocus = True
                return

            # ==============================================================================
            #             Face has been added - assume that the last selection entity is the one added
            # ==============================================================================
            input.commandInputs.itemById(EDGE_SELECT).isVisible = True
            input.commandInputs.itemById(EDGE_SELECT).hasFocus = True

            selectionDict = {
                hash(
                    s.selection(i).entity.entityToken
                ): s.selection(i).entity
                for i in range(s.selectionCount)
            }

            addedFaces = set(self.selectedFaces.keys()) ^ set(
                selectionDict.keys()
            )  # get difference -> results in

            for faceId in addedFaces:
                changedEntity = selectionDict[
                    faceId
                ]  # changedInput.selection(changedInput.selectionCount-1).entity
                activeOccurrenceId = (
                    hash(changedEntity.assemblyContext.entityToken)
                    if changedEntity.assemblyContext
                    else hash(changedEntity.body.entityToken)
                )

                faces = self.selectedOccurrences.get(activeOccurrenceId, [])

                faces += (
                    t := [
                        DbFace(
                            parent=self,
                            face=changedEntity,
                            params=self.param,
                            commandInputsEdgeSelect=input.commandInputs.itemById(
                                EDGE_SELECT
                            ),
                        )
                    ]
                )
                self.selectedOccurrences[
                    activeOccurrenceId
                ] = faces  # adds a face to a list of faces associated with this occurrence
                self.selectedFaces.update({faceObj.faceId: faceObj for faceObj in t})
                [self.selectedFaces[faceId].selectAll() for faceId in addedFaces]
                input.commandInputs.itemById(FACE_SELECT).hasFocus = True
            return
            # end of processing faces
        # ==============================================================================
        #         Processing changed edge selection
        # ==============================================================================

        if len(self.selectedEdges) > s.selectionCount:
            # ==============================================================================
            #             an edge has been removed
            # ==============================================================================

            changedSelectionList = [
                s.selection(i).entity
                for i in range(s.selectionCount)
            ]
            changedEdgeIdSet = set(
                map(calcId, changedSelectionList)
            )  # converts list of edges to a list of their edgeIds
            missingEdges = set(self.selectedEdges.keys()) - changedEdgeIdSet
            [self.selectedEdges[missingEdge].deselect() for missingEdge in missingEdges]
            # Note - let the user manually unselect the face if they want to choose a different face

            return
            # End of processing removed edge
        else:
            # ==============================================================================
            #         Start of adding a selected edge
            #         Edge has been added - assume that the last selection entity is the one added
            # ==============================================================================
            edge: adsk.fusion.BRepEdge = input.selection(
                input.selectionCount - 1
            ).entity
            self.selectedEdges[
                calcId(edge)
            ].select  # Get selectedFace then get selectedEdge, then call function

    def detection_mode(self):
        angleDetectionGroupInputs: adsk.core.GroupCommandInput = (
            self.inputs.addGroupCommandInput(ANGLE_DETECTION_GROUP, "Detection Mode")
        )
        angleDetectionGroupInputs.isExpanded = self.param.angleDetectionGroup
        angleDetectionGroupInputs.isVisible = (
            not self.param.parametric
        )  # disables angle selection if in parametric mode
        enableAcuteAngleInput: adsk.core.BoolValueCommandInput = (
            angleDetectionGroupInputs.children.addBoolValueInput(
                ACUTE_ANGLE, "Acute Angle", True, "", self.param.acuteAngle
            )
        )
        enableAcuteAngleInput.tooltip = (
            "Enables detection of corner angles less than 90"
        )
        minAngleSliderInput: adsk.core.FloatSliderCommandInput = (
            angleDetectionGroupInputs.children.addFloatSliderCommandInput(
                MIN_SLIDER, "Min Limit", "", 10.0, 89.0
            )
        )
        minAngleSliderInput.isVisible = self.param.acuteAngle
        minAngleSliderInput.valueOne = self.param.minAngleLimit
        enableObtuseAngleInput: adsk.core.BoolValueCommandInput = (
            angleDetectionGroupInputs.children.addBoolValueInput(
                OBTUSE_ANGLE, "Obtuse Angle", True, "", self.param.obtuseAngle
            )
        )  #
        enableObtuseAngleInput.tooltip = (
            "Enables detection of corner angles greater than 90"
        )
        maxAngleSliderInput: adsk.core.FloatSliderCommandInput = (
            angleDetectionGroupInputs.children.addFloatSliderCommandInput(
                MAX_SLIDER, "Max Limit", "", 91.0, 170.0
            )
        )
        maxAngleSliderInput.isVisible = self.param.obtuseAngle
        maxAngleSliderInput.valueOne = self.param.maxAngleLimit

    def mode(self):
        modeGroup: adsk.core.GroupCommandInput = self.inputs.addGroupCommandInput(
            MODE_GROUP, "Mode"
        )
        modeGroup.isExpanded = self.param.expandModeGroup
        modeGroupChildInputs = modeGroup.children
        modeRowInput: adsk.core.ButtonRowCommandInput = (
            modeGroupChildInputs.addButtonRowCommandInput(MODE_ROW, "Mode", False)
        )
        modeRowInput.listItems.add(
            STATIC, not self.param.parametric, "resources/staticMode"
        )
        modeRowInput.listItems.add(
            PARAMETRIC, self.param.parametric, "resources/parametricMode"
        )
        modeRowInput.tooltipDescription = (
            "Static dogbones do not move with the underlying component geometry. \n"
            "\nParametric dogbones will automatically adjust position with parametric changes to underlying geometry. "
            "Geometry changes must be made via the parametric dialog.\nFusion has more issues/bugs with these!"
        )
        typeRowInput: adsk.core.ButtonRowCommandInput = (
            modeGroupChildInputs.addButtonRowCommandInput(DOGBONE_TYPE, "Type", False)
        )
        typeRowInput.listItems.add(
            NORMAL_DOGBONE, self.param.dbType == NORMAL_DOGBONE, "resources/normal"
        )
        typeRowInput.listItems.add(
            MINIMAL_DOGBONE,
            self.param.dbType == MINIMAL_DOGBONE,
            "resources/minimal",
        )
        typeRowInput.listItems.add(
            MORTISE_DOGBONE,
            self.param.dbType == MORTISE_DOGBONE,
            "resources/hidden",
        )
        typeRowInput.tooltipDescription = (
            "Minimal dogbones creates visually less prominent dogbones, but results in an interference fit "
            "that, for example, will require a larger force to insert a tenon into a mortise.\n"
            "\nMortise dogbones create dogbones on the shortest sides, or the longest sides.\n"
            "A piece with a tenon can be used to hide them if they're not cut all the way through the workpiece."
        )
        mortiseRowInput: adsk.core.ButtonRowCommandInput = (
            modeGroupChildInputs.addButtonRowCommandInput(
                MORTISE_TYPE, "Mortise Type", False
            )
        )
        mortiseRowInput.listItems.add(
            ON_LONG_SIDE, self.param.longSide, "resources/hidden/longSide"
        )
        mortiseRowInput.listItems.add(
            ON_SHORT_SIDE, not self.param.longSide, "resources/hidden/shortside"
        )
        mortiseRowInput.tooltipDescription = (
            "Along Longest will have the dogbones cut into the longer sides."
            "\nAlong Shortest will have the dogbones cut into the shorter sides."
        )
        mortiseRowInput.isVisible = self.param.dbType == MORTISE_DOGBONE
        minPercentInp = modeGroupChildInputs.addValueInput(
            MINIMAL_PERCENT,
            "Percentage Reduction",
            "",
            adsk.core.ValueInput.createByReal(self.param.minimalPercent),
        )
        minPercentInp.tooltip = "Percentage of tool radius added to push out dogBone - leaves actual corner exposed"
        minPercentInp.tooltipDescription = "This should typically be left at 10%, but if the fit is too tight, it should be reduced"
        minPercentInp.isVisible = self.param.dbType == MINIMAL_DOGBONE
        depthRowInput: adsk.core.ButtonRowCommandInput = (
            modeGroupChildInputs.addButtonRowCommandInput(
                DEPTH_EXTENT, "Depth Extent", False
            )
        )
        depthRowInput.listItems.add(
            FROM_SELECTED_FACE, not self.param.fromTop, "resources/fromFace"
        )
        depthRowInput.listItems.add(
            FROM_TOP_FACE, self.param.fromTop, "resources/fromTop"
        )
        depthRowInput.tooltipDescription = (
            'When "From Top Face" is selected, all dogbones will be extended to the top most face\n'
            "\nThis is typically chosen when you don't want to, or can't do, double sided machining."
        )

    def settings(self):
        group: adsk.core.GroupCommandInput = self.inputs.addGroupCommandInput(
            SETTINGS_GROUP, "Settings"
        )
        group.isExpanded = self.param.expandSettingsGroup

        benchMark = group.children.addBoolValueInput(
            BENCHMARK, "Benchmark time", True, "", self.param.benchmark
        )
        benchMark.tooltip = "Enables benchmarking"
        benchMark.tooltipDescription = (
            "When enabled, shows overall time taken to process all selected dogbones."
        )

        log: adsk.core.DropDownCommandInput = (
            group.children.addDropDownCommandInput(
                LOGGING,
                "Logging level",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
        )
        log.tooltip = "Enables logging"
        log.tooltipDescription = (
            "Creates a dogbone.log file. \n"
            f"Location: {os.path.join(_appPath, 'dogBone.log')}"
        )

        log.listItems.add("Notset", self.param.logging == 0)
        log.listItems.add("Debug", self.param.logging == 10)
        log.listItems.add("Info", self.param.logging == 20)

    def offset(self):

        ui = self.inputs.addValueInput(
            TOOL_DIAMETER_OFFSET,
            "Tool diameter offset",
            _design.unitsManager.defaultLengthUnits,
            adsk.core.ValueInput.createByString(self.param.toolDiaOffsetStr),
        )
        ui.tooltip = "Increases the tool diameter"
        ui.tooltipDescription = (
            "Use this to create an oversized dogbone.\n"
            "Normally set to 0.  \n"
            "A value of .010 would increase the dogbone diameter by .010 \n"
            "Used when you want to keep the tool diameter and oversize value separate"
        )

    def tool_diameter(self):
        ui = self.inputs.addValueInput(
            TOOL_DIAMETER,
            "Tool Dia               ",
            _design.unitsManager.defaultLengthUnits,
            adsk.core.ValueInput.createByString(self.param.toolDiaStr),
        )
        ui.tooltip = "Size of the tool with which you'll cut the dogbone."

    def edge_select(self):
        ui = self.inputs.addSelectionInput(
            EDGE_SELECT,
            "DogBone Edges",
            "SELECT OR de-SELECT ANY internal edges dropping down FROM a selected face (TO apply dogbones TO",
        )
        ui.tooltip = "SELECT OR de-SELECT ANY internal edges dropping down FROM a selected face (TO apply dogbones TO)"
        ui.addSelectionFilter("LinearEdges")
        ui.setSelectionLimits(1, 0)
        ui.isVisible = False

    def face_select(self, ):
        ui = self.inputs.addSelectionInput(
            FACE_SELECT,
            "Face",
            "Select a face to apply dogbones to all internal corner edges",
        )
        ui.tooltip = "Select a face to apply dogbones to all internal corner edges\n*** Select faces by clicking on them. DO NOT DRAG SELECT! ***"
        ui.addSelectionFilter("PlanarFaces")
        ui.setSelectionLimits(1, 0)
