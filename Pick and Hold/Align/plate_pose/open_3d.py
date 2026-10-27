"""Export the existing offline visualization and open it in the default browser."""
from html.parser import HTMLParser
import os
from pathlib import Path
import subprocess
import sys

output=Path(__file__).parent/'demo_output'
renderer=Path('C:/Users/Cephla/.codex/plugins/cache/openai-bundled/visualize/1.0.37/skills/visualize/scripts/render.py')
preview=output/'plate-scene-preview.html'
subprocess.run([sys.executable,'-B',str(renderer),str(output/'plate-scene-3d.html'),str(preview),'--force'],check=True)

class Frame(HTMLParser):
    content=None
    def handle_starttag(self,tag,attrs):
        if tag=='iframe':self.content=dict(attrs).get('srcdoc')

frame=Frame();frame.feed(preview.read_text(encoding='utf-8'))
if not frame.content:raise RuntimeError('Rendered scene missing')
# A direct standalone document avoids local-file iframe restrictions.
standalone=output/'plate-scene-browser.html'
standalone.write_text(frame.content,encoding='utf-8')
os.startfile(str(standalone.resolve()))
print('Opened '+str(standalone.resolve()))
