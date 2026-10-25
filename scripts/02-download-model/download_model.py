"""Download the pinned Roman model; never execute repository-supplied code."""
from concurrent.futures import ThreadPoolExecutor
import json
# Allow this entry point to run directly as well as through run.sh.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.shared'))
from paths import ROOT, MODELS

def main():
    import requests
    config=json.loads((ROOT/'scripts/02-download-model/roman_model.json').read_text())
    revisions={v['repo']:v['revision'] for v in config.values()}
    provenance=MODELS/'revisions.json'
    if provenance.exists() and json.loads(provenance.read_text())!=revisions:
        raise SystemExit('Model revision differs. Use a fresh model directory before changing the pinned revisions.')
    def download(job):
        folder,spec,name=job
        dest=MODELS/folder/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.is_file() and dest.stat().st_size:
            print(f'[SKIP] {name}',flush=True)
            return
        url=f'https://huggingface.co/{spec["repo"]}/resolve/{spec["revision"]}/{name}'
        with requests.get(url,stream=True,timeout=120) as response:
            response.raise_for_status()
            part=dest.with_suffix(dest.suffix+'.part')
            with part.open('wb') as handle:
                for chunk in response.iter_content(8*1024*1024):handle.write(chunk)
            part.replace(dest)
        print(f'[DONE] {name}',flush=True)
    jobs=[(folder,spec,name) for folder,spec in config.items() for name in spec['files']]
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(download,jobs))
    provenance.write_text(json.dumps(revisions,indent=2))

if __name__=='__main__':main()
