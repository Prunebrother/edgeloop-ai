"""Static observation fixture only: no session progression or control API."""
import time
from ai_observer.observation import BrowserObservation
class ObservationFixture(BrowserObservation):
    def __init__(self,clock=time.monotonic,*unused):
        super().__init__(clock)
        self.report={'session_id':'00000000-0000-4000-8000-000000000001','status':'IDLE','seconds':0,
            'experience':'classic','active_mode':'classic','goal':'tease','hr':None,'effective_max':140,'pullback':140,
            'trend':'unknown','edges':0,'intensity':100,'movement':{'primary':0,'secondary':0,'stroke_min':0,'stroke_max':100},
            'devices':{'simulated_hr':True,'hr_ready':True,'toy_ready':False,'ble':False,'handy':False,'intiface':False,'tcode':False,'vacuglide':False},
            'safety':{'signal':'ok','no_contact':False,'watchdog_paused':False,'fault':'device_unready'}}
        self.received=clock();self.connected=True
