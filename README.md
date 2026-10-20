# FormaFlow 文件格式转换网站

FastAPI + 原生 HTML/CSS/JS + Docker。响应式莫兰迪蓝 UI、批量文件上传、按格式筛选转换选项、服务器实际转换、下载、临时文件自动清理。

## 项目结构

```text
formaflow/
├── app/
│   ├── __init__.py
│   └── main.py
├── static/
│   └── index.html
├── Dockerfile
├── .dockerignore
├── requirements.txt
└── README.md
```

## Docker 本地运行

```bash
docker build -t formaflow .
docker run --rm -p 10000:10000 -e MAX_UPLOAD_MB=100 formaflow
```

打开 http://localhost:10000

## Render 部署

1. 新建 GitHub 仓库，上传本项目目录中的全部文件（注意保留 app/ 和 static/ 目录）。
2. Render → New → Web Service → Connect GitHub 仓库。
3. Runtime 选择 Docker（Dockerfile 位于仓库根目录）。
4. 环境变量 `MAX_UPLOAD_MB=100`（可选），使用平台自动设置的 `PORT`。
5. 部署成功后访问 Render 分配的域名。

**注意：** Docker 镜像因包含 LibreOffice、Calibre 和 FFmpeg 会比较大，构建需要时间和资源；Render 的免费实例可能有内存、磁盘、请求大小及休眠限制，不保证适合大型文件转换。生产部署建议配置 1–2 GB 以上内存并通过反向代理限制请求大小。

## API

- `GET /api/formats` 支持格式与已安装工具
- `GET /api/targets/{ext}` 给定扩展名的可选目标
- `POST /api/convert` multipart `file`, `target`
- `GET /api/download/{id}` 下载转换结果
- `DELETE /api/jobs/{id}` 删除临时文件

## 当前限制与安全提示

- 转换结果临时存储于操作系统临时目录，**仅在新上传请求时清理过期任务**，不是独立定时清理器。容器重启会丢失文件。
- 当前实现不是针对不可信公开流量的生产级沙箱。公网开放前应加入限流、身份认证/验证码、隔离容器、磁盘配额、并发隔离和定时清理；转换器解析不可信文件存在风险。
- 下载链接带随机 ID，未登录者只要知道 URL 也能下载；不要上传敏感文件。
- 当前没有 ZIP 批量下载功能，转换结果需逐个下载。
- 目标列表是引擎级候选，不代表每一对格式都可成功；例如复杂 PDF、受 DRM 保护电子书、字体/压缩格式不保证支持。
- 图像动画、视频编码、文档版式、字幕等可能在转换中丢失。
