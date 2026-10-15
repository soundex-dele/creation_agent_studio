"""Supported transcription capability for trusted application packages."""


_EXPORTS = {'transcribe_audio': ('core.transcription', 'transcribe_audio'),
 'transcribe_segments': ('core.transcription', 'transcribe_segments'),
 'whisper_model': ('core.transcription', 'whisper_model')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)
