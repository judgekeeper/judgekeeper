# Third-party notices

judgekeeper's example reports in `docs/examples/` use five public datasets. The datasets themselves are not in this repository: the loaders in `docs/examples/jailbreakbench/` and `docs/examples/ragtruth/`, and `scripts/real_data_check.py`, download them from their sources at a pinned revision. The repository holds only ids, grades, counts and ranges derived from them, and judgekeeper's own judge verdicts on LLMBar.

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

## LLMBar

- **Used in:** `docs/examples/real-data-check/` (the judge verdicts are in `docs/examples/real-data-check/sources/llmbar-haiku.json`).
- **Source:** https://github.com/princeton-nlp/LLMBar (revision `900616bff90b6c6c8e1681f7d079250637c55992`).
- **Citation:** Zhiyuan Zeng, Jiatong Yu, Tianyu Gao, Yu Meng, Tanya Goyal and Danqi Chen. "Evaluating Large Language Models at Evaluating Instruction Following." ICLR 2024.
- **License:**

```
MIT License

Copyright (c) 2023 Princeton Natural Language Processing

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

## MT-Bench human judgments

- **Used in:** `docs/examples/real-data-check/`.
- **Source:** https://huggingface.co/datasets/lmsys/mt_bench_human_judgments (revision `f7d2896d2cc5d80f8b55c2bbc722613555233c25`).
- **Citation:** Lianmin Zheng, Wei-Lin Chiang, Ying Sheng, Siyuan Zhuang, Zhanghao Wu, Yonghao Zhuang, Zi Lin, Zhuohan Li, Dacheng Li, Eric P. Xing, Hao Zhang, Joseph E. Gonzalez and Ion Stoica. "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena." NeurIPS 2023 Datasets and Benchmarks Track. arXiv:2306.05685.
- **License:** CC-BY-4.0 (Creative Commons Attribution 4.0 International, https://creativecommons.org/licenses/by/4.0/). Attribution is required: the dataset is by the authors above, from the source above. Changed here: each item is turned into one yes/no question, as `docs/examples/real-data-check/report.md` describes. No data is copied into this repository.

## LLMJudge benchmark

- **Used in:** `docs/examples/real-data-check/`.
- **Source:** https://github.com/llm4eval/LLMJudge-benchmark (revision `0e2024814e3192cfc662ecee56dbd16b2536a7de`).
- **Citation:** Hossein A. Rahmani, Clemencia Siro, Mohammad Aliannejadi, Nick Craswell, Charles L. A. Clarke, Guglielmo Faggioli, Bhaskar Mitra, Paul Thomas and Emine Yilmaz. "Judging the Judges: A Collection of LLM-Generated Relevance Judgements." arXiv:2502.13908, 2025. The benchmark was first described in "LLMJudge: LLMs for Relevance Judgments", LLM4Eval workshop at SIGIR 2024.
- **License:**

```
MIT License

Copyright (c) 2023 LLMJudge-Benchmark

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

## Fonts

judgekeeper's report pages and the website use Manrope and JetBrains Mono, under the SIL Open Font License 1.1. The licence files ship next to the fonts, in `src/judgekeeper/fonts/` and `website/assets/fonts/`.
