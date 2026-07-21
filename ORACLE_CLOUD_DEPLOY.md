# 🔶 Oracle Cloud 注册与部署指南（永久免费方案）

> 目标：申请Oracle Cloud永久免费服务器，部署公务车管理系统
> 配置：1核CPU / 1GB内存 / 47GB硬盘（Always Free级别）
> 费用：永久免费（只要不升级配置）
> 前提：需要Visa或Mastercard信用卡（仅验证，不扣费）

═════════════════════════════════════════════
## 一、注册 Oracle Cloud

### 1. 准备工作
- 一张Visa或Mastercard信用卡（银联单标不行）
- 一个邮箱（Gmail、QQ邮箱都可以）
- 你的手机号（收验证码）

### 2. 注册步骤

1. 打开 https://cloud.oracle.com/free
2. 点 "Start for Free"
3. 填写：
   - Name: 你的英文名（拼音也行）
   - Email: 你的邮箱
   - Password: 设一个强密码
4. 选择 Home Region: **Japan East (Tokyo)** 或 **Asia Southeast (Singapore)**
   ⚠️ 重要！选日本或新加坡，国内访问最快
   ⚠️ 选了之后不能改！
5. 验证手机号（收短信验证码）
6. 填写信用卡信息（仅验证身份，不会被扣费）
7. 等待审核（通常几分钟到几小时，偶尔需要1-2天）

### 3. 注册常见问题

Q: 提示注册失败/需要联系客服？
A: Oracle审核有时很严。建议：
   - 换个浏览器重试（Chrome隐私模式）
   - 换个邮箱重试
   - 等几小时再试
   - 实在不行考虑PythonAnywhere方案

Q: 信用卡验证扣了1美元？
A: 这是预授权，几天后会退回，不是真扣费。

═════════════════════════════════════════════
## 二、创建免费服务器

注册成功后：

1. 登录 https://cloud.oracle.com
2. 点左上角菜单 → Compute → Instances
3. 点 "Create Instance"
4. 配置：
   - Name: vehicle-mgmt
   - Image: Canonical Ubuntu 22.04（默认就行）
   - Shape: VM.Standard.E2.1.Micro（Always Free）⚠️ 确认标签有"Always Free"
   - SSH Key: 下载或上传SSH公钥
   
5. 点 Create
6. 等待2-3分钟，状态变为 Running

7. 记下以下信息：
   - Public IP Address: xxx.xxx.xxx.xxx
   - Username: ubuntu

═════════════════════════════════════════════
## 三、配置服务器

用SSH连接（需要从你的Termux执行）：

ssh -i ~/ssh-key.pem ubuntu@你的服务器IP

连接后执行以下命令：

### 1. 安装Python和依赖
sudo apt update
sudo apt install -y python3-pip python3-venv nginx

### 2. 部署项目
cd /home/ubuntu
mkdir vehicle-management
cd vehicle-management

# 然后把项目文件上传（用scp或git）

### 3. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install flask waitress

### 4. 初始化数据库
python3 -c "from app import app, init_db; app.app_context().__enter__; init_db()"

### 5. 配置Nginx反向代理
sudo tee /etc/nginx/sites-available/vehicle-mgmt << 'EOF'
server {
    listen 80;
    server_name 你的服务器IP;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static/ {
        alias /home/ubuntu/vehicle-management/static/;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/vehicle-mgmt /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

### 6. 创建系统服务（开机自启）
sudo tee /etc/systemd/system/vehicle-mgmt.service << 'EOF'
[Unit]
Description=Vehicle Management Flask App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/vehicle-management
ExecStart=/home/ubuntu/vehicle-management/venv/bin/waitress-serve --host=127.0.0.1 --port=8000 app:application
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable vehicle-mgmt
sudo systemctl start vehicle-mgmt

### 7. 访问测试
浏览器打开 http://你的服务器IP/
应该看到登录页面！

═════════════════════════════════════════════
## 四、从Termux上传项目文件

在Termux中执行：

# 方法1: scp上传整个目录
scp -i ~/ssh-key.pem -r ~/vehicle-management/app.py \
  ~/vehicle-management/templates/ \
  ~/vehicle-management/static/ \
  ~/vehicle-management/requirements.txt \
  ~/vehicle-management/.secret_key \
  ubuntu@服务器IP:/home/ubuntu/vehicle-management/

# 方法2: 先推到GitHub，然后在服务器上git clone

═════════════════════════════════════════════
## 五、Oracle Cloud vs PythonAnywhere 对比

| 对比项 | Oracle Cloud | PythonAnywhere |
|--------|-------------|----------------|
| 费用 | 永久免费 | 永久免费 |
| CPU | 1核（全天可用） | 每天100秒 |
| 内存 | 1GB | 共享（很少） |
| 磁盘 | 47GB | 512MB |
| 国内访问 | 快（东京节点） | 较快 |
| 注册难度 | 难（需信用卡） | 容易（只需邮箱） |
| 部署难度 | 中等（需SSH配置） | 简单（网页操作） |
| 适合场景 | 长期正式使用 | 快速上线/试用 |

═════════════════════════════════════════════
## 六、建议路线

1. 今天：注册PythonAnywhere → 15分钟上线 → 马上能用
2. 本周：尝试注册Oracle Cloud → 成功后迁移
3. 最终：Oracle Cloud做主服务，PythonAnywhere做备用

两个方案的部署指南都已准备好：
- ~/vehicle-management/PYTHONANYWHERE_DEPLOY.md
- ~/vehicle-management/ORACLE_CLOUD_DEPLOY.md（本文件）
