"""Behavioral checks for independent actors and the pure cutout transforms."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from animation2d.episode03.engine import Actor, AssetError, CAST, REQUIRED_BONES, attachment_transform, production_readiness, render_frame
from animation2d.episode03.kinematics import camera_point, ik, place, rot, walk_foot


class KinematicsTests(unittest.TestCase):
    def test_clamped_ik_preserves_both_bones(self):
        for target in [(0,0),(1,1),(10000,-50),(50,100)]:
            for bend in (-1,1):
                elbow,wrist=ik([0,0],target,135,125,bend)
                self.assertAlmostEqual(np.linalg.norm(elbow),135,places=6)
                self.assertAlmostEqual(np.linalg.norm(wrist-elbow),125,places=6)
                self.assertTrue(np.isfinite(wrist).all())
        with self.assertRaises(ValueError):ik([0,0],[1,1],0,125)

    def test_pivot_transform_and_camera_are_consistent(self):
        sprite=Image.new('RGBA',(21,21))
        for x in range(8,13):
            for y in range(8,13):sprite.putpixel((x,y),(255,0,0,255))
        canvas=Image.new('RGBA',(200,200))
        place(canvas,sprite,[10,10],[100,80],90,2)
        self.assertEqual(canvas.getpixel((100,80)),(255,0,0,255))
        np.testing.assert_allclose(camera_point([960,540],{'zoom':2,'center':[960,540]},(960,540)),[480,270])
        np.testing.assert_allclose(camera_point([1060,540],{'zoom':2,'center':[960,540]},(960,540)),[580,270])

    def test_walk_stance_stays_planted_as_body_advances(self):
        positions=[walk_foot([x,0],-30,1,'left',500,96) for x in range(10,60)]
        self.assertLess(np.ptp([p[0] for p in positions]),1e-9)
        self.assertTrue(all(p[1]==500 for p in positions))


class MultiActorTests(unittest.TestCase):
    def manifest(self):
        return {'canvas':[1920,1080],'characters':{name:{} for name in CAST},'shots':[{
            'id':'SHOT_001','duration':15,'cast':['DAN','MAYA','NINA'],'camera':{'zoom':1,'center':[960,540]},
            'actors':{name:{'position':[550+i*400,600],'scale':.65,'depth':100,
                'action':{'kind':'idle'}} for i,name in enumerate(['DAN','MAYA','NINA'])},'props':[]}]}

    def test_independent_actor_cues_and_placement(self):
        dan=Actor('DAN',placement={'position':[100,200]},cues=[{'start':0,'end':1,'value':'D'}])
        maya=Actor('MAYA',placement={'position':[700,200]},cues=[{'start':1,'end':2,'value':'B'}])
        self.assertEqual(dan.mouth_shape(.5),'D')
        self.assertEqual(maya.mouth_shape(.5),'X')
        self.assertEqual(dan.mouth_shape(1.5),'X')
        self.assertEqual(maya.mouth_shape(1.5),'B')
        np.testing.assert_allclose(maya.pose(.5)['root']-dan.pose(.5)['root'],[600,0])
        dan.placement['scale']=2
        self.assertEqual(maya.pose(.5)['scale'],1)
        for cue in [{'start':0,'end':1,'value':'Z'}, {'start':0,'end':1,'value':None}, {'value':'D'}, {'start':0,'end':float('nan'),'value':'A'}]:
            with self.assertRaises(AssetError):Actor('DAN',cues=[cue])

    def test_attachment_follows_solved_wrist_not_unreachable_target(self):
        actor=Actor('DAN',placement={'position':[800,500],'scale':.8,
            'action':{'kind':'reach','hand':'left','target':[-10000,-2000]}})
        hand=actor.solved_hand(14,'left')
        attached=attachment_transform(actor,14,{'hand':'left','offset':[20,5],'rotation':13})
        np.testing.assert_allclose(attached.position,hand.position+rot(np.array([20,5])*.8,hand.rotation))
        self.assertAlmostEqual(attached.rotation,hand.rotation+13)
        self.assertGreater(np.linalg.norm(hand.position-np.array([-10000,-2000])),1000)
        early=attachment_transform(actor,0,{'hand':'left'})
        self.assertGreater(np.linalg.norm(attached.position-early.position),50)

    def test_render_uses_stable_prop_depth_and_camera(self):
        manifest=self.manifest()
        shot=manifest['shots'][0]
        shot['cast']=[]
        shot['actors']={}
        shot['props']=[{'id':'red','position':[960,540],'size':[120,120],'color':'#FF0000','depth':10},
                       {'id':'blue','position':[960,540],'size':[120,120],'color':'#0000FF','depth':20}]
        result=render_frame(manifest,'SHOT_001',0,size=(960,540))
        self.assertEqual(result.getpixel((480,270)),(0,0,255))
        shot['props'][0]['depth']=30
        self.assertEqual(render_frame(manifest,'SHOT_001',0).getpixel((480,270)),(255,0,0))
        shot['props'][0]['depth']=20  # Equal depth: insertion order remains deterministic.
        self.assertEqual(render_frame(manifest,'SHOT_001',0).getpixel((480,270)),(0,0,255))
        shot['camera']={'zoom':2,'center':[860,540]}
        shifted=render_frame(manifest,'SHOT_001',0)
        self.assertEqual(shifted.getpixel((580,270)),(0,0,255))
        self.assertNotEqual(shifted.getpixel((480,270)),(0,0,255))

    def test_blocking_schematics_and_production_reject_missing_art(self):
        manifest=self.manifest()
        frame=render_frame(manifest,'SHOT_001',0)
        self.assertEqual(frame.mode,'RGB')
        self.assertEqual(frame.size,(960,540))
        self.assertEqual(len(production_readiness(manifest,'SHOT_001')),3)
        with self.assertRaisesRegex(AssetError,'production requires'):
            render_frame(manifest,'SHOT_001',0,mode='production')
        with self.assertRaises(ValueError):render_frame(manifest,'SHOT_001',15)
        with self.assertRaises(ValueError):render_frame(manifest,'NO_SHOT',0)


    def test_actor_and_foreground_depth_do_not_depend_on_cast_name(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            manifest=self.manifest();manifest['__base_dir__']=str(folder)
            shot=manifest['shots'][0];shot['cast']=['DAN','MAYA']
            for name in shot['cast']:
                shot['actors'][name]={'position':[960,650],'scale':1,'depth':10,'action':{'kind':'idle'}}
            # Equal depths use declared cast order, so Maya's torso covers Dan's.
            self.assertEqual(render_frame(manifest,'SHOT_001',0).getpixel((480,275)),(120,53,84))
            shot['actors']['DAN']['depth']=20
            self.assertEqual(render_frame(manifest,'SHOT_001',0).getpixel((480,275)),(77,155,208))
            mask=Image.new('RGBA',(40,40),'#00FF00');mask.save(folder/'foreground.png')
            shot['foreground']=[{'file':'foreground.png','position':[940,530],'depth':1000}]
            self.assertEqual(render_frame(manifest,'SHOT_001',0).getpixel((480,275)),(0,255,0))

    def test_real_png_rig_loader_and_actor_specific_cue_files(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            sprite=Image.new('RGBA',(30,30))
            for x in range(4,26):
                for y in range(4,26):sprite.putpixel((x,y),(210,70,40,255))
            sprite.save(folder/'part.png')
            rig={'version':1,'parts':[{'id':bone,'bone':bone,'file':'part.png','pivot':[15,15],
                                      'depth':i} for i,bone in enumerate(sorted(REQUIRED_BONES))],
                 'faces':{'D':'part.png'}}
            (folder/'rig.json').write_text(json.dumps(rig))
            manifest=self.manifest();manifest['__base_dir__']=str(folder)
            manifest['shots'][0]['cast']=['DAN']
            manifest['characters']['DAN']={'rig':'rig.json'}
            cues=folder/'audio/SHOT_001';cues.mkdir(parents=True)
            (cues/'DAN.cues.json').write_text(json.dumps({'mouthCues':[{'start':0,'end':1,'value':'D'}]}))
            frame=render_frame(manifest,'SHOT_001',.5,mode='production',audio_dir=folder/'audio')
            self.assertEqual(frame.mode,'RGB')
            self.assertEqual(production_readiness(manifest,'SHOT_001',folder/'audio'),[])
            rig['faces']={}
            (folder/'rig.json').write_text(json.dumps(rig))
            with self.assertRaisesRegex(AssetError,'missing authored mouth sprites'):
                render_frame(manifest,'SHOT_001',0,mode='production',audio_dir=folder/'audio')
            self.assertTrue(production_readiness(manifest,'SHOT_001',folder/'audio'))
            rig['parts'].pop()
            (folder/'rig.json').write_text(json.dumps(rig))
            with self.assertRaisesRegex(AssetError,'incomplete'):
                render_frame(manifest,'SHOT_001',.5,mode='production')
            rig['parts'][0]['file']='../outside.png'
            (folder/'rig.json').write_text(json.dumps(rig))
            with self.assertRaisesRegex(AssetError,'inside the rig folder'):
                render_frame(manifest,'SHOT_001',.5,mode='production')


if __name__=='__main__':unittest.main()
