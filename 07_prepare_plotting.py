"""可选：为当前项目虚拟环境准备绘图库，再运行07_plot_project.py。

首次安装需要联网。仅在当前项目内的.venv-olist或.venv中执行安装。
安装临时文件和绘图缓存放在项目目录，关闭pip下载缓存。
"""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
os.environ["MPLCONFIGDIR"] = str(ROOT / ".plot_cache")


def main():
    try:
        import matplotlib
        print(f"绘图环境已可用：Matplotlib {matplotlib.__version__}。")
        print("现在可以打开07_plot_project.py，点击右上角运行。")
        return
    except ImportError:
        pass
    prefix = Path(sys.prefix).resolve()
    if sys.prefix == sys.base_prefix or prefix.parent != ROOT or prefix.name not in {".venv-olist", ".venv"}:
        raise SystemExit("请先在VS Code选择本项目.venv-olist或.venv里的Python解释器，再运行本准备脚本。")
    temporary = ROOT / ".plot_setup_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    install_env = dict(os.environ, TMP=str(temporary), TEMP=str(temporary), PIP_DISABLE_PIP_VERSION_CHECK="1")
    print(f"安装到当前项目环境：{sys.executable}")
    print(f"安装临时目录：{temporary}；pip下载缓存已关闭。首次安装需要联网。", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", str(ROOT / "requirements-plotting.txt")], env=install_env, check=True)
    subprocess.run([sys.executable, "-c", "import matplotlib; print('Matplotlib '+matplotlib.__version__+' 已就绪。')"], env=install_env, check=True)
    print("准备完成。接下来打开07_plot_project.py，点击右上角运行。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"绘图环境尚未准备完成：{exc}\n请保留终端错误截图。图包内预先生成的PNG仍可直接打开。") from exc
