# PDF 解析与证据引擎

使用 Python 3.11+、PyMuPDF 和 paper 的 core 接口。可从相邻的 [paper 工作区](https://github.com/xylograph-xg/paper/blob/main/README.md)使用已有测试解释器运行：

```sh
PYTHONPATH=infrastructure/bootstrap:. infrastructure/environments/test/bin/python -c 'from read.api import parser__parse_pdf; import sys; print(parser__parse_pdf(sys.argv[1]).page_count)' 原文.pdf
```

`parser__parse_pdf` 读取 PDF，返回页数、逐页文本及证据候选。无文字层的页可能没有文本，路径不存在会抛出异常。解析不启动模型。导出接口按调用参数写入工作目录，默认使用宿主已有的阅读数据。模型相关接口沿用 paper 的暂停与权限检查。

[源码、依赖与完整接口](read/README.md) · [阅读工作流](https://github.com/xylograph-xg/paper/blob/main/workbench/reading/README.md)
