# Private data manifest

All paths below are local, ignored by Git and absent from tracked history.
Permitted use for this session: owner-authorized classification, OCR/provider
evaluation and 0606 parser development. No private file was imported into the
public repository or exported.

## Student scripts

| File | SHA-256 | Detected group/syllabus | Imported into learner data? |
|---|---|---|---|
| `student_scripts/20260422125354420_0001.pdf` | `fd90de8489a132136cf6564de8db2076f976d3cf2caa99b127011245d419da51` | group 125354420, 0580/04 M/J 2025 | No |
| `student_scripts/20260422125354420_0002 (1).pdf` | `4a4d604a8341df76eb26acebfbdbd8522daa8c6a1a4a1b4e4b23e47bd7244fc7` | group 125354420, 0580/04 M/J 2025 | No |
| `student_scripts/20260422135002935_0001.pdf` | `4d45cbc5c95215bec28c836350a99cbb283ef99f80fdc7bce8610cb752e86637` | group 135002935, 0580/02 M/J 2025 | No; page 1 used for authorized OCR test |
| `student_scripts/20260422135002935_0002 (1).pdf` | `5448308affe09d78fd9abfb4729e56127d8c682707454febad7edf70e01752dd` | group 135002935, 0580/02 M/J 2025 | No |

Storage root:
`private_test_data/student_scripts/`.

## Official 0606 packs

| File | SHA-256 | Use |
|---|---|---|
| `0606_w25_qp_11 (1).pdf` | `48d54ee3b40f190fe578ca8922db7769aaf082605b6088414f15fb4dfbbce8ec` | registered component 11 |
| `0606_w25_ms_11 (1).pdf` | `dc3f8f40c0129221d8fdfd9a856227efa07c5134fc2b816f00cd91d47f065b55` | parsed, review required |
| `0606_w25_qp_12 (1).pdf` | `49075aee68e192d6efe45de7566dc9a8e320192475766da59040b08536d01094` | registered component 12 |
| `0606_w25_ms_12 (1).pdf` | `43565aaad54594566e1a5dfeb20b6e1548a07a318e07da274d98435eba91b1f5` | parsed, review required |
| `0606_w25_qp_13 (1).pdf` | `1114fdf383e88a07d26ec0b178004dcfbfe8bae1865489b611bf2357bdf816f6` | registered component 13 |
| `0606_w25_ms_13 (1).pdf` | `62f2200e6e8a0a43deb3cb290d3481ac36b101c427e9320dbad606b37a9cffc6` | parsed, review required |
| `0606_w25_gt.pdf` | `66d8cd4f3ae3bdddd4e8c7e40bf3d018ecb1620c60462f67a6b641d78c4bd793` | threshold provenance only |

Storage root:
`private_test_data/official_0606/`.

The database stores local references, hashes and parser output. It does not
copy PDF bytes. The database itself is ignored and not a deployable fixture.
