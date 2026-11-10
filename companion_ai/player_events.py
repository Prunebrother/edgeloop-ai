# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded read-only Player evidence and conversational card intentions."""
import re
import unicodedata
from urllib.parse import unquote, urlsplit
from pydantic import Field, field_validator, model_validator
from typing import Literal
from .models import StrictModel

PLAYER_EVENTS=frozenset({'player_opened','video_selected','video_started'})
PLAYER_COUNTER={'player_opened':'opened','video_selected':'selected','video_started':'started'}
PLAYER_BRIEFS={
    'player_opened':'React only to the user opening the Player workspace, not selecting a video or pressing Play. Offer your own anticipation of watching together, without another introduction.',
    'video_selected':'React to the user selecting a video for shared viewing, using its supplied title only if useful. Express your own curiosity or taste without inventing its contents or claiming to have watched it.',
    'video_started':'Acknowledge the confirmed start of shared viewing with a brief personal reaction. Express anticipation, not a review or narration of unseen images. Invent no video content, participant appearance or physiological effects.',
}

class PlayerFacts(StrictModel):
    instance_id: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    opened: int = Field(ge=0,le=1000000)
    selected: int = Field(ge=0,le=1000000)
    started: int = Field(ge=0,le=1000000)
    workspace_open: bool
    has_video: bool
    playing: bool
    title: str | None = Field(default=None,max_length=160)
    title_source: Literal['filename','metadata','unknown'] = 'unknown'

    @field_validator('title')
    @classmethod
    def no_paths(cls,value):
        if value is None:return None
        # Defence in depth for older/custom clients; only a leaf label reaches prompts.
        if '://' in value:value=urlsplit(value).path
        value=re.split(r'[/\\]',unquote(value))[-1].split('?')[0].split('#')[0]
        value=''.join(c for c in value if unicodedata.category(c) not in {'Cc','Cf'}).strip()
        return value or None


    @model_validator(mode='after')
    def consistent(self):
        if self.playing and (not self.has_video or not self.selected or not self.started):raise ValueError('Playback requires selected media and a confirmed start')
        return self


def player_evidence(kind,previous,current,gap=False):
    if gap or not previous:return None
    p=(previous.get('details') or {}).get('player');r=(current.get('details') or {}).get('player')
    if not p or not r or p['instance_id']!=r['instance_id']:return None
    counter=PLAYER_COUNTER[kind]
    if r[counter]<=p[counter]:return None
    if kind=='player_opened' and not r['workspace_open']:return None
    if kind!='player_opened' and (not r['has_video'] or r['selected']==0):return None
    if kind=='video_started' and not r['playing']:return None
    return {'player_opened':'User explicitly opened the Player workspace.',
            'video_selected':'User selected a new video; title is a label, not evidence of video contents.',
            'video_started':'The media lifecycle confirmed playback started; no video contents or physiological effects observed.'}[kind]


def player_current(event,report):
    current=(report.get('details') or {}).get('player') or {};original=event.get('player') or {}
    if not original or any(current.get(k)!=original.get(k) for k in ('instance_id','title','has_video')):return False
    if event['kind']=='player_opened':return current.get('workspace_open') and current.get('opened')==original.get('opened') and current.get('selected')==original.get('selected')
    return current.get('has_video') and current.get('selected')==original.get('selected') and (event['kind']!='video_selected' or current.get('started')==original.get('started')) and (event['kind']!='video_started' or current.get('playing') and current.get('started')==original.get('started'))
