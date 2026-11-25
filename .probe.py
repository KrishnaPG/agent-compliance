import subprocess,sys,tempfile,shutil
from pathlib import Path
D = Path(tempfile.mkdtemp()); (D/'.brick-harness/packets').mkdir(parents=True)
shutil.copy('harness/acceptance/fixtures/packet/toy_item/mechanical.json', D/'.brick-harness/packets/toy_item.json')
p=subprocess.run([sys.executable,str(Path('bin/bh').resolve()),'step','assemble_packet','--item','toy_item'],cwd=D,capture_output=True,text=True,env={'PYTHONPATH':str(Path('lib').resolve()),'PATH':'/usr/bin'})
print(p.returncode,p.stdout[:200],p.stderr[-500:])
