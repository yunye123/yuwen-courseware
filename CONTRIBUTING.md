# Contributing

Issues and pull requests should improve the reusable workflow, templates, tests or documentation. By contributing, you confirm that your contribution is original or properly licensed, that you have the right to submit it, and that it is offered under the repository's [个人学习与参考许可](LICENSE).

Do not contribute textbooks, curriculum-standard full text, teacher cases, classroom recordings, student information, proprietary screenshots, account data, secrets, generated lesson deliverables, or material whose redistribution rights are unclear. Use synthetic or clearly redistributable fixtures in tests.

Before opening a pull request, run:

```bash
python3 -m unittest discover -s tests -q
rg -n 'references/[k]nowledge|assets/[b]enchmarks|private-self[-]use|/[U]sers/' . --glob '!.git/**'
```

The scan must have no findings. Keep changes focused, document any new external dependency, and do not add binaries without maintainer approval.

Do not submit content under a license that conflicts with the personal-learning, no-redistribution or non-commercial restrictions of this repository.
