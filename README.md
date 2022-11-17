# DiplomacyAMR
AMR-related aspects of Diplomacy ALLAN project

## Links to related resources
* AMR Editor: https://www.isi.edu/~ulf/amr/AMR-editor.html
* AMR guidelines: https://github.com/amrisi/amr-guidelines/blob/master/amr.md
* AMR Dictionary: https://www.isi.edu/~ulf/amr/lib/amr-dict.html (also available via AMR Editor)
    * Diplomacy appendix: https://www.isi.edu/~ulf/amr/lib/amr-dict-diplomacy.html
* AMR Diplomacy Google Doc: https://docs.google.com/document/d/1DEvS4PUiPjR1SURfCzeOAk2rO7VyZXXhkUa4bFH2XLA

## amr-to-daide.py

### Usage &nbsp; (click below for details)
<details>
<summary>CLI argument structure</summary>

```
usage: amr-to-daide.py [-h] [-i AMR-INPUT-FILENAME] [-o OUTPUT-FILENAME] [-j JSONL-OUTPUT-FILENAME] [-m MAX] [-d] [-v]

Maps AMR to DAIDE in classical or jsonl format

options:
  -h, --help            show this help message and exit
  -i AMR-INPUT-FILENAME, --input AMR-INPUT-FILENAME
  -o OUTPUT-FILENAME, --output OUTPUT-FILENAME
                        (default: STDOUT)
  -j JSONL-OUTPUT-FILENAME, --json JSONL-OUTPUT-FILENAME
                        (default: None)
  -m MAX, --max MAX     (maximum number of AMRs in ouput)
  -d, --developer_mode
  -v, --verbose         write change log etc. to STDERR
```
</details>

<details>
<summary>CLI examples</summary>

```
cd DiplomacyAMR/annotations
../code/amr-to-daide.py -i dip-all-amr-smosher.txt --max 10
../code/amr-to-daide.py -i dip-all-amr-smosher.txt -o dip-all-amr-daide-smosher.txt -j dip-all-amr-daide-smosher.jsonl
``` 
</details>
