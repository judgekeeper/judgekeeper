# Third-party notices

judgekeeper's example reports in `docs/examples/` use two public datasets. The datasets themselves are not in this repository: the loaders in `docs/examples/jailbreakbench/` and `docs/examples/ragtruth/` download them from their sources at a pinned revision. The repository holds only ids, grades, counts and ranges derived from them.

## JailbreakBench

- **Used in:** `docs/examples/jailbreakbench/`.
- **Source:** https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors (config `judge_comparison`, revision `886acc352a31533ffbcf4ef22c744658688086fc`); code and license: https://github.com/JailbreakBench/jailbreakbench
- **Citation:** Patrick Chao, Edoardo Debenedetti, Alexander Robey, Maksym Andriushchenko, Francesco Croce, Vikash Sehwag, Edgar Dobriban, Nicolas Flammarion, George J. Pappas, Florian Tramèr, Hamed Hassani and Eric Wong. "JailbreakBench: An Open Robustness Benchmark for Jailbreaking Large Language Models." NeurIPS 2024 Datasets and Benchmarks Track. arXiv:2404.01318.
- **License:**

```
MIT License

Copyright (c) 2023 JailbreakBench Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## RAGTruth

- **Used in:** `docs/examples/ragtruth/` and `docs/examples/probes/`.
- **Source:** https://github.com/ParticleMedia/RAGTruth (commit `c103204b9ce28d6bbad859304bf30de72b8ed8fe`, files `dataset/response.jsonl` and `dataset/source_info.jsonl`).
- **Citation:** Cheng Niu, Yuanhao Wu, Juno Zhu, Siliang Xu, Kashun Shum, Randy Zhong, Juntong Song and Tong Zhang. "RAGTruth: A Hallucination Corpus for Developing Trustworthy Retrieval-Augmented Language Models." ACL 2024. arXiv:2401.00396.
- **License:**

```
MIT License

Copyright (c) 2023 Particle Media

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
