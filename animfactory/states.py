"""Reusable, seekable timeline state graphs compiled into the existing ActionMixer.

No second pose solver or mutable playback clock. The source graph is stored in
each project's motion_library.machines registry, and actors reference it with
frame-accurate replace/overlay steps. Compilation is a PURE FUNCTION: the same
frame produces identical actions regardless of prior sampling or job order.
"""
from __future__ import annotations

from copy import deepcopy

from .schema import MOTION_KINDS, number, point, valid_id

PARAMETERS = frozenset({
    "target","targets","object","hand","speed","weight","priority",
    "emotion","degrees","lean","wrist_rotation","hold_last","source",
})
STEP_PARAMETERS = PARAMETERS - {"source"}
EMOTIONS = frozenset(("neutral","happy","sad","angry","surprised",
                      "curious","excited","worried"))


def _reject(message):
    raise ValueError("Invalid AnimFactory state machine: " + message)


def _action(source, *, allow_clip=True):
    if not isinstance(source, dict) or not source:
        _reject("State action must be a JSON object")
    allowed = PARAMETERS | {"clip"} if allow_clip else STEP_PARAMETERS
    if set(source) - allowed:
        _reject("Unknown or unsafe state action parameter")
    if allow_clip and source.get("clip") not in MOTION_KINDS:
        _reject("State action clip must use an existing reusable motion")
    if "source" in source and (not isinstance(source["source"], str)
                               or not source["source"]):
        _reject("Named source must be a nonempty string")
    if source.get("clip") in ("keyframed","pose") and not source.get("source"):
        _reject("Keyframed and pose actions require source")
    if "target" in source:
        point(source["target"], "state.target")
    if "targets" in source:
        targets=source["targets"]
        if not isinstance(targets,dict) or not set(targets)<= {"left","right"}:
            _reject("Hand targets must map left/right")
        for value in targets.values():
            point(value,"state.hand.target")
    if "hand" in source and source["hand"] not in ("left","right"):
        _reject("Hand must be left or right")
    if "object" in source and (not isinstance(source["object"],str) or
                                not source["object"]):
        _reject("Object must name an existing prop")
    if "emotion" in source and source["emotion"] not in EMOTIONS:
        _reject("Unknown emotion")
    if "hold_last" in source and type(source["hold_last"]) is not bool:
        _reject("hold_last must be boolean")
    for field in ("speed","weight","priority","degrees","lean","wrist_rotation"):
        if field in source:
            value=number(source[field],"state."+field)
            if field=="speed" and value<=0:
                _reject("Speed must be positive")
            if field=="weight" and not 0<=value<=1:
                _reject("Weight must be in 0..1")
    return deepcopy(source)


def validate_graph(source):
    if (not isinstance(source,dict) or source.get("version") != 1 or
        set(source) - {"version","states","allowed_transitions"}):
        _reject("State graph must use version 1 and states")
    states=source.get("states")
    if not isinstance(states,dict) or not states or len(states)>64:
        _reject("State graph must have 1..64 named states")
    for name,entry in states.items():
        valid_id(name,"state name")
        if not isinstance(entry,dict) or set(entry)!={"actions"}:
            _reject("A state must declare only its action list")
        actions=entry["actions"]
        if not isinstance(actions,list) or not 1<=len(actions)<=8:
            _reject("A state requires 1..8 reusable actions")
        for spec in actions:
            _action(spec)
    allowed=source.get("allowed_transitions")
    if allowed is not None:
        if not isinstance(allowed,list):
            _reject("allowed_transitions must be an array of state pairs")
        for pair in allowed:
            if (not isinstance(pair,list) or len(pair)!=2
                or any(not isinstance(x,str) or x not in states for x in pair)):
                _reject("Invalid state transition edge")
    return deepcopy(source)


def compile_machine(machine, library, fps, scene_frames):
    """Compile events to existing clip dicts using absolute frame times.

    replace: active until the next replace, never depends on past samples.
    overlay: concurrent clip interval with explicit duration_frames.
    Optional blend_frames creates the existing ActionMixer envelope, not a
    new independent interpolation algorithm.
    """
    if not isinstance(machine,dict) or set(machine)!={"source","steps"}:
        _reject("Actor machine must reference a named graph and steps")
    source=machine["source"]
    if not isinstance(source,str):
        _reject("Machine source must be a string")
    graphs=library.get("machines",{})
    if not isinstance(graphs,dict) or source not in graphs:
        _reject(f"Unknown reusable state graph: {source}")
    graph=validate_graph(graphs[source])
    steps=machine["steps"]
    if not isinstance(steps,list) or not 1<=len(steps)<=512:
        _reject("State steps must contain 1..512 events")
    if type(fps) is not int or fps<=0 or type(scene_frames) is not int or scene_frames<=0:
        _reject("Invalid project frame-rate or scene length")
    normal=[]
    previous_at=-1
    last_replace=None
    for i,raw in enumerate(steps):
        if not isinstance(raw,dict) or set(raw) - {
            "state","at_frame","mode","duration_frames","blend_frames","params"
        }:
            _reject(f"Event {i} has unknown fields")
        state=raw.get("state")
        if state not in graph["states"]:
            _reject("Event references unknown state")
        at=raw.get("at_frame")
        if type(at) is not int or not 0<=at<scene_frames or at<previous_at:
            _reject("Events must be chronological and within the scene")
        previous_at=at
        mode=raw.get("mode","replace")
        if mode not in ("replace","overlay"):
            _reject("Event mode must be replace or overlay")
        if mode=="replace":
            if last_replace is None and (i!=0 or at!=0):
                _reject("First replace state must begin at frame zero")
            if last_replace is not None:
                if at<=last_replace["at_frame"]:
                    _reject("Replacement states must be strictly ordered")
                allowed=graph.get("allowed_transitions")
                if allowed is not None and [last_replace["state"],state] not in allowed:
                    _reject("Replacement transition not permitted by graph")
            last_replace={"state":state,"at_frame":at}
        elif last_replace is None:
            _reject("An overlay requires an already active replace state")
        duration=raw.get("duration_frames")
        if mode=="overlay" and (type(duration) is not int or duration<1 or at+duration>scene_frames):
            _reject("Overlay requires a bounded positive duration_frames")
        if mode=="replace" and duration is not None:
            _reject("Replacement duration is determined by next state")
        blend=raw.get("blend_frames",0)
        if type(blend) is not int or blend<0:
            _reject("blend_frames must be nonnegative integer")
        params=_action(raw.get("params",{}),allow_clip=False) if raw.get("params") else {}
        normal.append({"state":state,"at_frame":at,"mode":mode,
                       "blend_frames":blend,"params":params,
                       "duration_frames":duration})
    if normal[0]["mode"]!="replace" or normal[0]["at_frame"]!=0:
        _reject("State timeline requires an initial replacement at frame 0")
    compiled=[]
    for index,event in enumerate(normal):
        begin=event["at_frame"]
        if event["mode"]=="overlay":
            end=begin+event["duration_frames"]
        else:
            end=next((step["at_frame"] for step in normal[index+1:]
                      if step["mode"]=="replace"),scene_frames)
        span=end-begin
        blend_frames=event["blend_frames"]
        if blend_frames*2>=span:
            _reject("Transition blend may not cover half or more of state span")
        for base in graph["states"][event["state"]]["actions"]:
            spec=deepcopy(base)
            spec.update(event["params"])
            spec["start"]=begin/fps
            spec["end"]=end/fps
            if blend_frames:
                spec["blend"]=blend_frames/fps
            compiled.append(spec)
    return compiled
