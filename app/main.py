import asyncio, io, json, os, shutil, tempfile, time, uuid, zipfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
register_heif_opener()

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.gettempdir()) / 'formaflow-jobs'
WORK.mkdir(exist_ok=True)
MAX_BYTES = int(os.getenv('MAX_UPLOAD_MB','100')) * 1024 * 1024
TTL = 3600
MAX_PARALLEL = asyncio.Semaphore(2)
app = FastAPI(title='FormaFlow')
app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')

GROUPS = {
 'image': {'jpg','jpeg','png','webp','bmp','gif','tiff','tif','ico','avif','heic'},
 'audio': {'mp3','wav','flac','ogg','opus','aac','m4a','wma'},
 'video': {'mp4','mkv','mov','avi','webm','flv','wmv','gif'},
 'document': {'doc','docx','odt','rtf','txt','html','pdf'},
 'ebook': {'epub','mobi','azw3','fb2','txt','html','pdf'},
 'table': {'xlsx','xls','ods','csv','tsv'},
 'slides': {'pptx','ppt','odp','pdf'},
 'text': {'md','markdown','html','txt','rtf','docx','odt','epub'},
 'subtitle': {'srt','vtt','ass','ssa'},
 'data': {'json','yaml','yml','toml'},
}
OUTPUTS = {
 'image':['jpg','png','webp','bmp','gif','tiff','ico','avif'],
 'audio':['mp3','wav','flac','ogg','opus','aac','m4a'],
 'video':['mp4','mkv','mov','avi','webm','gif'],
 'document':['pdf','docx','odt','rtf','txt','html'],
 'ebook':['epub','mobi','azw3','fb2','pdf','txt'],
 'table':['xlsx','ods','csv','pdf'],
 'slides':['pptx','odp','pdf'],
 'text':['md','html','txt','docx','odt','epub','pdf'],
 'subtitle':['srt','vtt','ass','ssa'],
 'data':['json','yaml','toml']
}
IMAGE_FORMAT={'jpg':'JPEG','png':'PNG','webp':'WEBP','bmp':'BMP','gif':'GIF','tiff':'TIFF','ico':'ICO','avif':'AVIF'}
ALIASES={'jpeg':'jpg','tif':'tiff','markdown':'md','yml':'yaml'}

def canonical(s): return ALIASES.get(s.lower(),s.lower())
def available(cmd): return shutil.which(cmd) is not None

def routes(ext):
 ext=canonical(ext)
 result=set()
 for group, members in GROUPS.items():
  if ext not in members: continue
  if group=='image' and available('convert') or group=='image':
   result.update(OUTPUTS[group])
  elif group in ('audio','video') and available('ffmpeg'):
   result.update(OUTPUTS[group])
  elif group=='document' and available('libreoffice'):
   result.update(OUTPUTS[group])
  elif group=='ebook' and available('ebook-convert'):
   result.update(OUTPUTS[group])
  elif group=='table' and available('libreoffice'):
   result.update(OUTPUTS[group])
  elif group=='slides' and available('libreoffice'):
   result.update(OUTPUTS[group])
  elif group=='text' and available('pandoc'):
   result.update(OUTPUTS[group])
  elif group=='subtitle' and available('ffmpeg'):
   result.update(['srt','vtt','ass','ssa'])
  elif group=='data':
   result.update(OUTPUTS[group])
 result.discard(ext)
 # Conversions that have a concrete supported backend.
 if ext=='pdf': result &= {'epub','mobi','azw3','fb2'}
 if ext in {'jpg','png','webp','bmp','gif','tiff','ico','avif','heic'}:
  result &= set(IMAGE_FORMAT)
 if ext in GROUPS['subtitle']: result &= {'srt','vtt','ass','ssa'}
 if ext in GROUPS['video'] and ext!='gif': result.update(OUTPUTS['audio'])
 if ext in GROUPS['data']: result &= set(OUTPUTS['data'])
 if ext in GROUPS['text'] and not available('pandoc'): result -= set(OUTPUTS['text'])
 return sorted(result)

async def command(*args, timeout=120):
 try:
  p=await asyncio.create_subprocess_exec(*map(str,args),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
  try: out,err=await asyncio.wait_for(p.communicate(),timeout)
  except asyncio.TimeoutError:
   p.kill(); await p.communicate(); raise ValueError('转换超时，请尝试较小的文件')
  if p.returncode: raise ValueError(err.decode(errors='replace')[-800:] or '转换程序执行失败')
 except FileNotFoundError: raise ValueError('服务器尚未安装此转换引擎')

async def convert(src, dest, ext, target):
 if ext in GROUPS['image'] and target in IMAGE_FORMAT:
  def image_convert():
   with Image.open(src) as im:
    im=ImageOps.exif_transpose(im)
    if target=='jpg':
     if im.mode in ('RGBA','LA') or ('transparency' in im.info):
      bg=Image.new('RGB',im.size,'white'); bg.paste(im,mask=im.convert('RGBA').getchannel('A')); im=bg
     else: im=im.convert('RGB')
    elif target=='ico': im.thumbnail((256,256))
    im.save(dest,format=IMAGE_FORMAT[target])
  await asyncio.to_thread(image_convert)
 elif ext in GROUPS['data'] and target in OUTPUTS['data']:
  def data_convert():
   import tomllib
   try: import yaml
   except ImportError: yaml=None
   raw=src.read_text(encoding='utf-8-sig')
   if ext=='json': obj=json.loads(raw)
   elif ext=='toml': obj=tomllib.loads(raw)
   else:
    if yaml is None: raise ValueError('需要安装 PyYAML')
    obj=yaml.safe_load(raw)
   if target=='json': data=json.dumps(obj,ensure_ascii=False,indent=2)
   elif target=='yaml':
    if yaml is None: raise ValueError('需要安装 PyYAML')
    data=yaml.safe_dump(obj,allow_unicode=True,sort_keys=False)
   else:
    import tomli_w
    data=tomli_w.dumps(obj)
   dest.write_text(data,encoding='utf-8')
  await asyncio.to_thread(data_convert)
 elif ext in GROUPS['subtitle'] and target in OUTPUTS['subtitle']:
  await command('ffmpeg','-nostdin','-y','-i',src,dest)
 elif ext in GROUPS['video'] and target in OUTPUTS['video']:
  await command('ffmpeg','-nostdin','-y','-i',src,dest)
 elif ext in GROUPS['audio'] and target in OUTPUTS['audio']:
  await command('ffmpeg','-nostdin','-y','-i',src,dest)
 elif ext in GROUPS['video'] and target in OUTPUTS['audio']:
  await command('ffmpeg','-nostdin','-y','-i',src,'-vn',dest)
 elif ext in GROUPS['ebook'] and target in OUTPUTS['ebook'] and ext not in {'doc','docx','odt'}:
  await command('ebook-convert',src,dest)
 elif ext in GROUPS['text'] and target in OUTPUTS['text'] and ext not in {'pdf','docx','odt','rtf'}:
  fmt={'md':'markdown','txt':'plain','html':'html','docx':'docx','odt':'odt','epub':'epub','rtf':'rtf','pdf':'pdf'}.get(target,target)
  await command('pandoc',src,'-o',dest,timeout=120)
 elif ext in GROUPS['document'] | GROUPS['table'] | GROUPS['slides']:
  if target in {'txt','html','pdf','docx','odt','rtf','xlsx','ods','csv','pptx','odp'}:
   profile=src.parent/'lo-profile'
   await command('libreoffice',f'-env:UserInstallation=file://{profile}','--headless','--convert-to',target,'--outdir',dest.parent,src)
  else: raise ValueError('不支持的文档转换方向')
 else: raise ValueError('没有适合这两个格式的转换引擎')
 if not dest.exists() or dest.stat().st_size==0: raise ValueError('未生成有效文件，可能是不兼容的格式组合')

def clean():
 for folder in WORK.iterdir():
  try:
   if folder.is_dir() and time.time()-folder.stat().st_mtime>TTL: shutil.rmtree(folder,ignore_errors=True)
  except OSError: pass

@app.get('/')
async def index(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/formats')
async def formats():
 return {'groups':{k:sorted(v) for k,v in GROUPS.items()},'engines':{c:available(c) for c in ['ffmpeg','libreoffice','ebook-convert','pandoc']},'max_upload_mb':MAX_BYTES//1048576}

@app.get('/api/targets/{extension}')
async def targets(extension:str): return {'targets':routes(extension)}

@app.post('/api/convert')
async def upload(file:UploadFile=File(...), target:str=Form(...)):
 clean()
 name=Path(file.filename or 'file').name
 ext=canonical(Path(name).suffix.lstrip('.'))
 target=canonical(target.strip().lstrip('.'))
 if not ext or target not in routes(ext): raise HTTPException(400,'不支持的转换格式组合')
 job=uuid.uuid4().hex
 folder=WORK/job; folder.mkdir(mode=0o700)
 src=folder/('input.'+ext)
 dest=folder/('output.'+target)
 try:
  total=0
  with src.open('wb') as f:
   while chunk:=await file.read(1024*1024):
    total+=len(chunk)
    if total>MAX_BYTES: raise HTTPException(413,'文件超过服务器上传大小限制')
    f.write(chunk)
  async with MAX_PARALLEL:
   await convert(src,dest,ext,target)
  src.unlink(missing_ok=True)
  return {'id':job,'name':Path(name).stem+'.'+target,'bytes':dest.stat().st_size,'download':'/api/download/'+job}
 except HTTPException:
  shutil.rmtree(folder,ignore_errors=True); raise
 except Exception as e:
  shutil.rmtree(folder,ignore_errors=True)
  raise HTTPException(422,str(e))

@app.get('/api/download/{job}')
async def download(job:str):
 if len(job)!=32 or not all(c in '0123456789abcdef' for c in job): raise HTTPException(404)
 folder=WORK/job
 if not folder.is_dir(): raise HTTPException(404,'文件已过期')
 files=list(folder.glob('output.*'))
 if not files: raise HTTPException(404)
 return FileResponse(files[0],filename='converted'+files[0].suffix,media_type='application/octet-stream')

@app.delete('/api/jobs/{job}')
async def delete(job:str):
 if len(job)!=32 or not all(c in '0123456789abcdef' for c in job): raise HTTPException(404)
 shutil.rmtree(WORK/job,ignore_errors=True)
 return {'ok':True}


@app.post('/api/images-to-epub')
async def images_to_epub(files: list[UploadFile] = File(...), title: str = Form('我的画册'), direction: str = Form('ltr')):
 if not 1 <= len(files) <= 150: raise HTTPException(400,'请选择 1 到 150 张图片')
 if direction not in ('ltr','rtl'): raise HTTPException(400,'阅读方向无效')
 clean()
 job=uuid.uuid4().hex; folder=WORK/job; folder.mkdir(mode=0o700)
 try:
  pictures=[]; total=0
  for idx, f in enumerate(files):
   suffix=Path(f.filename or '').suffix.lower()
   if suffix not in ('.png','.jpg','.jpeg','.webp','.bmp','.gif','.tif','.tiff','.heic','.avif'):
    raise ValueError('包含不支持的图片格式：'+suffix)
   content=await f.read(MAX_BYTES+1)
   total+=len(content)
   if total>MAX_BYTES: raise ValueError('所有图片合计不能超过上传限制')
   def normalize(data):
    with Image.open(io.BytesIO(data)) as im:
     im=ImageOps.exif_transpose(im)
     if im.width*im.height>50000000: raise ValueError('单张图片像素过大')
     if getattr(im,'n_frames',1)>1: im.seek(0)
     out=io.BytesIO()
     if im.mode not in ('RGB','RGBA'): im=im.convert('RGBA')
     im.save(out,format='PNG',optimize=True)
     return out.getvalue(),im.size
   blob,size=await asyncio.to_thread(normalize,content)
   pictures.append((blob,size))
  import html
  book_title=html.escape(title.strip()[:100] or '我的画册')
  dest=folder/'output.epub'
  identifier='urn:uuid:'+str(uuid.uuid4())
  with zipfile.ZipFile(dest,'w') as z:
   z.writestr('mimetype','application/epub+zip',compress_type=zipfile.ZIP_STORED)
   z.writestr('META-INF/container.xml','<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
   manifest=[]; spine=[]; nav=[]
   for i,(blob,(w,h)) in enumerate(pictures,1):
    name=f'page{i:04d}'
    z.writestr(f'OEBPS/images/{name}.png',blob)
    page=f'''<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{book_title} - {i}</title><meta name="viewport" content="width={w},height={h}"/><style>html,body{{margin:0;padding:0}}img{{display:block;width:100%;height:auto}}</style></head><body><div><img src="images/{name}.png" alt="Page {i}"/></div></body></html>'''
    z.writestr(f'OEBPS/{name}.xhtml',page)
    manifest.extend([f'<item id="{name}" href="{name}.xhtml" media-type="application/xhtml+xml"/>',f'<item id="img{i}" href="images/{name}.png" media-type="image/png"/>'])
    spine.append(f'<itemref idref="{name}"/>')
    nav.append(f'<li><a href="{name}.xhtml">第 {i} 页</a></li>')
   nav_doc='<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head><body><nav epub:type="toc" id="toc"><ol>'+''.join(nav)+'</ol></nav></body></html>'
   z.writestr('OEBPS/nav.xhtml',nav_doc)
   manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
   opf=f'''<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="zh"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">{identifier}</dc:identifier><dc:title>{book_title}</dc:title><dc:language>zh</dc:language><meta property="dcterms:modified">{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}</meta></metadata><manifest>{''.join(manifest)}</manifest><spine page-progression-direction="{direction}">{''.join(spine)}</spine></package>'''
   z.writestr('OEBPS/content.opf',opf)
  return {'id':job,'name':'album.epub','bytes':dest.stat().st_size,'download':'/api/download/'+job}
 except Exception as e:
  shutil.rmtree(folder,ignore_errors=True)
  raise HTTPException(422,str(e))
