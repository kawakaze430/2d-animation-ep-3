"""Functional browser rig import/pivot editing contract with original synthetic art.

No AI inference, hidden-anatomy reconstruction, network model fetch or movie render.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import http.client
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image, ImageDraw

from animfactory import Project, EditSession
from animfactory.rigging import (
    PARTS, decode_layers, import_layers, rig_info, rig_warnings,
    commit_rig_edit, restore_rig_version, original_rig_preview, sprite_bytes
)
from animfactory.studio import handler_for, revision


def tiny_layer(bone, *, opaque=False):
    color = (120 + hash(bone)%50, 75, 145, 255)
    im = Image.new("RGBA", (36, 52), (0,0,0,255) if opaque else (0,0,0,0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((6,5,30,47),radius=6,fill=color)
    d.ellipse((12,12,22,20),fill="#e0bea2")
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class RigAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project.create(Path(self.temp.name)/"project", "independent_test",
                                      "My Independent Character", canvas=(160,90), fps=12)
        self.layers = {bone:tiny_layer(bone) for bone in PARTS}

    def imported(self, name="JUNO"):
        import_layers(self.project,name,self.layers,source="original-synthetic-test",
                      license="original-test-art")
        return rig_info(self.project,name)

    def test_exact_semantic_layers_and_rejection_without_side_effects(self):
        doc=deepcopy(self.project.doc)
        with self.assertRaisesRegex(ValueError, "complete set of 15"):
            import_layers(self.project,"JUNO",{"head":self.layers["head"]})
        self.assertEqual(doc,self.project.doc)
        bad=deepcopy(self.layers)
        bad["hand.left"]=tiny_layer("hand.left",opaque=True)
        with self.assertRaisesRegex(ValueError, "transparent"):
            import_layers(self.project,"JUNO",bad)
        bad=deepcopy(self.layers)
        bad["pelvis"]=b"not a real PNG"
        with self.assertRaises(ValueError):
            import_layers(self.project,"JUNO",bad)
        self.assertEqual(doc,self.project.doc)

    def test_import_15_preserves_original_png_provenance_and_rig_schema(self):
        result=self.imported()
        rig=result["rig"]
        self.assertEqual(set(p["bone"] for p in rig["parts"]),set(PARTS))
        self.assertEqual(rig["version"],1)
        self.assertEqual(result["source"],"original-synthetic-test")
        self.assertEqual(result["license"],"original-test-art")
        self.assertEqual(result["active_version"],"rig.json")
        self.assertEqual(len(self.project.doc["assets"]),1)
        asset=self.project.doc["assets"]["JUNO_rig"]
        self.assertEqual(len(asset["files"]),16)
        self.assertTrue(self.project.verify_assets())
        for part in rig["parts"]:
            self.assertEqual(sprite_bytes(self.project,"JUNO",part["bone"]),self.layers[part["bone"]])
        self.assertIsInstance(result["warnings"],list)
        self.assertTrue(any("mouth" in warning for warning in result["warnings"]))

    def test_geometry_edit_saves_immutable_revision_and_changes_authoritative_frame(self):
        original=self.imported()
        before_bytes=(self.project.root/"assets/rigs/JUNO/rig.json").read_bytes()
        png_before=original_rig_preview(self.project,"JUNO").tobytes()
        result=commit_rig_edit(self.project,"JUNO",{
            "kind":"part","bone":"head",
            "changes":{"pivot":[8,12],"source_end":[18,45],"depth":55,"mirror":True}
        })
        self.assertEqual(result["active_version"][:9],"rig_edit_")
        self.assertEqual(len(result["versions"]),2)
        self.assertEqual(next(p for p in result["rig"]["parts"] if p["bone"]=="head")["pivot"],[8.,12.])
        self.assertEqual(before_bytes,(self.project.root/"assets/rigs/JUNO/rig.json").read_bytes())
        self.assertNotEqual(png_before,original_rig_preview(self.project,"JUNO").tobytes())
        reloaded=Project.open(self.project.root)
        self.assertEqual(rig_info(reloaded,"JUNO")["active_version"],result["active_version"])
        self.assertTrue(reloaded.verify_assets())
        # Technical IK preview uses same part sprites and geometry, with a reach action.
        self.assertEqual(original_rig_preview(reloaded,"JUNO",movement=True).size,(600,500))

    def test_undo_redo_and_version_restore_survive_reload(self):
        initial=self.imported()
        before=deepcopy(self.project.doc)
        session=EditSession(self.project)
        updated=commit_rig_edit(self.project,"JUNO",{
            "kind":"anchor","name":"shoulder_left","value":[-75,-150]})
        session.record_external(before)
        self.assertEqual(updated["rig"]["anchors"]["shoulder_left"],[-75.,-150.])
        self.assertTrue(session.can_undo)
        session.undo()
        self.assertEqual(rig_info(self.project,"JUNO")["active_version"],"rig.json")
        self.assertEqual(Project.open(self.project.root).doc,self.project.doc)
        session.redo()
        self.assertEqual(rig_info(self.project,"JUNO")["active_version"],updated["active_version"])
        restore_rig_version(self.project,"JUNO","rig.json")
        self.assertEqual(rig_info(Project.open(self.project.root),"JUNO")["active_version"],"rig.json")
        self.assertTrue(self.project.verify_assets())
        self.assertEqual(initial["rig"],rig_info(self.project,"JUNO")["rig"])

    def test_invalid_pivot_bone_and_unsafe_restoration_never_write(self):
        self.imported()
        original=deepcopy(self.project.doc)
        edits=[
            {"kind":"part","bone":"not_a_bone","changes":{"pivot":[1,2]}},
            {"kind":"part","bone":"head","changes":{"file":"/etc/shadow"}},
            {"kind":"part","bone":"head","changes":{"pivot":[1000,10]}},
            {"kind":"part","bone":"head","changes":{"pivot":[15,10],"source_end":[15,10]}},
            {"kind":"anchor","name":"traversal","value":[1,2]},
            {"kind":"length","name":"upper_arm","value":-10},
            {"kind":"length","name":"shin","value":"one"},
        ]
        for change in edits:
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):
                commit_rig_edit(self.project,"JUNO",change)
            self.assertEqual(self.project.doc,original)
        with self.assertRaises(ValueError):
            restore_rig_version(self.project,"JUNO","../../etc/passwd")

    def test_decode_layers_requires_valid_base64_and_no_extra_roles(self):
        encoded={bone:base64.b64encode(raw).decode("ascii") for bone,raw in self.layers.items()}
        self.assertEqual(decode_layers(encoded),self.layers)
        encoded["extra_role"]=encoded["head"]
        with self.assertRaisesRegex(ValueError,"exactly 15"):
            decode_layers(encoded)
        del encoded["extra_role"]
        encoded["head"]="%%%invalid%%%"
        with self.assertRaisesRegex(ValueError,"base64"):
            decode_layers(encoded)

    def test_local_http_layers_import_edit_undo_and_protected_assets(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(self.project))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(3)))
        conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=12)
        self.addCleanup(conn.close)
        def req(method,route,payload=None,headers=None):
            data=None if payload is None else json.dumps(payload).encode("utf-8")
            conn.request(method,route,body=data,headers=headers or {})
            res=conn.getresponse()
            return res.status,res.read()
        status,data=req("GET","/api/project")
        rev=json.loads(data)["revision"]
        encoded={bone:base64.b64encode(raw).decode() for bone,raw in self.layers.items()}
        upload={"revision":rev,"character":"JUNO","source":"original","license":"CC0-test","layers":encoded}
        status,body=req("POST","/api/rig/import",upload,{"Content-Type":"application/json"})
        self.assertEqual(status,200,body)
        payload=json.loads(body)
        self.assertEqual(len(payload["project"]["characters"]),1)
        self.assertNotEqual(payload["revision"],rev)
        status,part=req("GET","/api/rig-image?character=JUNO&bone=head")
        self.assertEqual(status,200)
        self.assertEqual(part,self.layers["head"])
        status,part=req("GET","/api/rig-preview?character=JUNO&movement=1")
        self.assertEqual(status,200)
        self.assertTrue(part.startswith(b"\x89PNG"))
        status,doc=req("GET","/api/rig?character=JUNO")
        self.assertEqual(status,200)
        self.assertEqual(json.loads(doc)["rig"]["active_version"],"rig.json")
        change={"revision":payload["revision"],"character":"JUNO",
                "edit":{"kind":"part","bone":"head","changes":{"pivot":[8,12]}}}
        status,body=req("POST","/api/rig/edit",change,{"Content-Type":"application/json"})
        self.assertEqual(status,200,body)
        changed=json.loads(body)
        self.assertTrue(changed["undo"])
        status,body=req("POST","/api/rig/edit",change,{"Content-Type":"application/json"})
        self.assertEqual(status,409)  # stale project revision
        status,body=req("POST","/api/undo",{"revision":changed["revision"]},
                         {"Content-Type":"application/json"})
        self.assertEqual(status,200,body)
        self.assertEqual(rig_info(Project.open(self.project.root),"JUNO")["active_version"],"rig.json")
        status,_=req("GET","/api/rig-image?character=JUNO&bone=../../etc/passwd")
        self.assertEqual(status,400)
        status,_=req("POST","/api/rig/edit",{"revision":"fake","character":"JUNO","edit":change["edit"]},
                      {"Content-Type":"application/json","Origin":"https://evil.invalid"})
        self.assertEqual(status,403)

    def test_rig_keys_cannot_escape_saved_project_registry(self):
        self.imported()
        initial=deepcopy(self.project.doc)
        with self.assertRaises(ValueError):
            commit_rig_edit(self.project,"JUNO",{"kind":"part","bone":"head",
                                                  "changes":{"path":"../escape"}})
        self.assertEqual(self.project.doc,initial)
        self.assertTrue(self.project.verify_assets())


if __name__=="__main__":
    unittest.main()
