# 把这个软件发布到 GitHub（照抄即可）

> 目标：让别人（和你自己换电脑时）能一条命令拿到这个行情条。
> 下面命令在 `G:\mydeepseek\crypto-ticker` 目录里执行。

---

## ⚠️ 发布前必须先做的一件事：确认密钥没进仓库

`config.json` 里有你的 **QQ 邮箱授权码**（`alert_mail.password`）。
它已经被写进 `.gitignore`，但**务必自己再验一次**：

```powershell
git status --short          # 输出里不该出现 config.json
git check-ignore -v config.json
# 期望看到：.gitignore:2:config.json	config.json
```

如果不小心已经提交过，**换一个 QQ 授权码**（QQ邮箱 → 设置 → 账户 →
重新生成授权码），再按下面「清掉历史里的密钥」处理。

---

## 1. 本地建仓库并提交

```powershell
cd G:\mydeepseek\crypto-ticker
git init
git add .
git status --short          # 再确认一眼：没有 config.json / ticker.log
git commit -m "行情条 v0.19：透明悬浮行情窗 + 全品种扫盘 + 趋势线 + 主题皮肤"
```

## 2. 在 GitHub 上建一个空仓库

浏览器打开 <https://github.com/new>：

- **Repository name**：`crypto-ticker`（随便，别用中文）
- **Public / Private**：自己选（想给别人用就 Public）
- **不要**勾 "Add a README / .gitignore / license"（我们本地已经有了）
- 点 **Create repository**，然后复制它给的 HTTPS 地址，形如
  `https://github.com/你的用户名/crypto-ticker.git`

## 3. 关联并推送

```powershell
git branch -M main
git remote add origin https://github.com/你的用户名/crypto-ticker.git
git push -u origin main
```

第一次推送会弹浏览器让你登录 GitHub（或要你填 **Personal Access Token** 当密码，
GitHub 早就不收账号密码了：Settings → Developer settings → Personal access tokens → 勾 `repo`）。

## 4. 以后每次改完怎么更新

```powershell
cd G:\mydeepseek\crypto-ticker
git add .
git commit -m "改了什么"
git push
```

---

## 换一台电脑怎么用

**方式 A：装了 Python（推荐，改起来方便）**

```powershell
git clone https://github.com/你的用户名/crypto-ticker.git
cd crypto-ticker
copy config.example.json config.json     # 第一次要有配置文件
python ticker.py                          # 或双击 启动.vbs（无控制台）
```

**方式 B：不装 Python（直接用 exe）**

在本机双击 `打包exe.bat` 生成 `dist\行情条.exe`，把**这一个文件**拷到别的电脑，
双击就能跑（图表库已经打包进去了，目标机器不需要 Python、不需要联网装任何东西）。

也可以把 exe 传到 GitHub 的 **Releases** 里，别人直接下载：
仓库页 → Releases → Draft a new release → 填版本号 → 把 `行情条.exe` 拖进去 → Publish。

---

## 想省事：装 GitHub CLI

```powershell
winget install --id GitHub.cli
gh auth login
gh repo create crypto-ticker --public --source . --push
```

一条命令建仓库 + 推送，不用手点网页。

---

## 清掉历史里的密钥（只有已经提交过才需要）

```powershell
# 最省事的办法：整个仓库重新开始
Remove-Item -Recurse -Force .git
git init
git add .
git commit -m "init"
# 然后重新 add remote + push（会覆盖远端历史，自己的仓库无所谓）
git push -f -u origin main
```
