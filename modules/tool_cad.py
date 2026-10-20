"""Yerel OpenSCAD → STL; sabit komut, açık onay ve yeni çıktı dosyası."""
from modules.tool_slicer import _LocalTool

_TOOL = _LocalTool('cad', 'OpenSCAD', ('openscad',), {'.scad'}, '.stl',
                   lambda source, output: ['-o', output, source])
run, status, cancel = _TOOL.run, _TOOL.status, _TOOL.cancel
CONTRACT = _TOOL.contract('box')
