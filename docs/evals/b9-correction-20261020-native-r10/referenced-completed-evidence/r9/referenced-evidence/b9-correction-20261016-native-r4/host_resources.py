"""Read-only Windows backing-host resource observation for the WSL campaign."""
import ctypes
import json
import time

class Memory(ctypes.Structure):
    _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong),
        *[(name,ctypes.c_ulonglong) for name in ('total','available','page_total','page_available',
            'virtual_total','virtual_available','extended')]]

memory=Memory()
memory.length=ctypes.sizeof(memory)
if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
    raise OSError('GlobalMemoryStatusEx failed')
print(json.dumps({'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
    'physical_total':memory.total,'physical_available':memory.available,'page_available':memory.page_available}))
