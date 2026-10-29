"""AGPL-3.0-only. Explicit loopback configuration; no discovery fallback or daemon startup."""
from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]

def validate_ollama_url(value):
    try:
        url=urlsplit(value)
        port=url.port
    except (ValueError,TypeError) as exc:
        raise ValueError('Ollama URL must be a loopback HTTP origin with a valid port') from exc
    if not isinstance(value,str):raise ValueError('Ollama URL must be a string')
    if url.netloc.endswith(':'):raise ValueError('Ollama URL must have a valid port')
    if url.scheme!='http' or url.hostname not in {'127.0.0.1','localhost','::1'} or url.username is not None or url.password is not None or url.path not in {'','/'} or url.query or url.fragment or port is not None and not 1<=port<=65535:
        raise ValueError('Ollama URL must be a loopback HTTP origin without credentials, paths or query parameters')
    return value.rstrip('/')

@dataclass(frozen=True)
class RuntimeConfig:
    ollama_url: str
    port: int
    data_dir: Path
    config_path: Path
    thinking: bool = False
    explicit_expressions: bool = True

    @classmethod
    def load(cls,environ=None):
        env=os.environ if environ is None else environ
        path=Path(env.get('EDGELOOP_AI_CONFIG',ROOT/'config/ai.toml'))
        if not path.is_file():raise ValueError(f'AI configuration file not found: {path}')
        values=tomllib.loads(path.read_text())
        if not isinstance(values.get('ollama',{}),dict):raise ValueError('The ollama configuration must be a TOML table')
        if set(values)-{'ollama','inference'} or set(values.get('ollama',{}))-{'url'}:raise ValueError('Unsupported AI configuration key')
        inference=values.get('inference',{})
        if not isinstance(inference,dict) or set(inference)-{'thinking','explicit_expressions'}:
            raise ValueError('Unsupported inference configuration')
        if inference.get('thinking',False) is not False:
            raise ValueError('F2.5 requires inference.thinking = false')
        if type(inference.get('explicit_expressions',True)) is not bool:
            raise ValueError('inference.explicit_expressions must be boolean')
        url=validate_ollama_url(env.get('EDGELOOP_OLLAMA_URL',values.get('ollama',{}).get('url','http://127.0.0.1:11435')))
        try:port=int(env.get('EDGELOOP_OBSERVER_PORT','8768'))
        except ValueError as exc:raise ValueError('EDGELOOP_OBSERVER_PORT must be an integer') from exc
        if not 1<=port<=65535:raise ValueError('EDGELOOP_OBSERVER_PORT must be between 1 and 65535')
        return cls(url,port,Path(env.get('EDGELOOP_FORK_AI_DATA',ROOT/'.ai-data')),path,False,inference.get('explicit_expressions',True))
