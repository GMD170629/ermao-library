# 官网反馈接收服务

独立 FastAPI 服务，仅由官网 Nginx 代理 `/api/feedback`。应用后端将已登录用户的反馈发送到该地址；浏览器不接触 SMTP 凭据。

## 配置

复制 `receiver.env.example` 到服务器的受限配置文件，填写收件 Google 邮箱与 SMTP 凭据。配置文件和数据库不得放入网站静态目录或仓库。`FEEDBACK_DATA_ROOT` 需由运行用户可写，SQLite 数据库长期保存编号、正文、联系方式、所选诊断信息和发送状态；附件不存入数据库。Google 邮箱中的已送达附件由邮箱自身保存。

本地启动：在本目录安装项目后运行 `uvicorn receiver.app:create_app --factory --host 127.0.0.1 --port 8787`。`GET /health` 用于健康检查。首次启动由 SQLAlchemy ORM 创建独立数据库；后续结构变化应增加迁移，不能改写已有数据。

## 部署

官网现用宝塔管理。接收服务作为独立 Python 项目 `ermao-feedback` 部署在 `/opt/ermao-feedback`，由宝塔的 `ermao-feedback` Python 3.12 虚拟环境安装本项目，运行用户为 `www`，只监听 `127.0.0.1:8787`。数据目录是 `/opt/ermao-feedback/data`，SMTP 发件账号为 QQ 邮箱，收件地址为 `gamersguyu@gmail.com`；授权码只配置在宝塔服务端环境变量中。宝塔负责项目的启动和重启，官网的 Node 项目仍独立运行。

其他站点若使用 Compose，可把 `Dockerfile` 构建为同栈独立服务，映射 `127.0.0.1:8787:8787`，将受限环境文件传入容器，并挂载可写数据卷到 `/var/lib/ermao-feedback`。未使用宝塔的独立进程部署可在 `/opt/ermao-feedback` 建立 Python 虚拟环境，安装本项目，以专用 `feedback` 用户运行，并用 systemd 管理：

```ini
[Unit]
Description=Ermao official feedback receiver
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=feedback
Group=feedback
WorkingDirectory=/opt/ermao-feedback
EnvironmentFile=/etc/ermao-feedback/receiver.env
ExecStart=/opt/ermao-feedback/.venv/bin/uvicorn receiver.app:create_app --factory --host 127.0.0.1 --port 8787 --proxy-headers --forwarded-allow-ips=*
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/ermao-feedback

[Install]
WantedBy=multi-user.target
```

在 **现有** `www.embook.xyz` HTTPS server 中加入以下 location，保留原站点其他配置：

```nginx
location = /api/feedback {
    client_max_body_size 17m;
    proxy_pass http://127.0.0.1:8787/api/feedback;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_connect_timeout 5s;
    proxy_read_timeout 45s;
}
```

服务自带按来源地址的小时级限速；Nginx 覆盖 `X-Forwarded-For` 为实际客户端地址，服务只信任此代理传入的来源。上线时也应在 Nginx 层为公开入口设置按真实客户端 IP 的请求限速。不要将服务端口直接暴露到公网。若 Nginx 和服务在不同网络命名空间，`proxy_pass` 目标需改为仅内网可达的服务地址。

## 文件与重试

每次最多 5 个图片、PDF、TXT、LOG 或 ZIP 文件，单个 10 MB、合计 15 MB。文件只在发送期间存在于 `temporary-files`，成功或失败后都删除；启动时清理中断遗留目录。相同提交键重复请求返回已发送的原编号；失败后同键、同内容可以重试。若 SMTP 已接收邮件但进程在更新数据库状态前中断，状态无法自动确认，人工核对邮件后再处理重试。

上线顺序：先部署接收端并验证 `/health`、测试邮件、记录和临时文件清理；再部署应用端与 Web 入口，并用不含私密信息的反馈核对完整链路。
