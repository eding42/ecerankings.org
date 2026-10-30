import unittest
from pipeline.harvest_dac_program import (
    normalize_title,
    parse_authors,
    parse_program_text,
    merge_program_papers,
)


class TestHarvestDacProgram(unittest.TestCase):
    def test_normalize_title(self):
        self.assertEqual(
            normalize_title("Fusedot: A Multiplication-Fused Dot Product!"),
            "fusedot a multiplication fused dot product",
        )

    def test_parse_authors_single_affil(self):
        author_str = (
            "Wenju Zhao, Huazhong University of Science and Technology; "
            "Jianhui Yue, Michigan Tech. University"
        )
        authors = parse_authors(author_str)
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0]["author_name"], "Wenju Zhao")
        self.assertEqual(
            authors[0]["raw_affiliations"],
            ["Huazhong University of Science and Technology"],
        )
        self.assertEqual(authors[1]["author_name"], "Jianhui Yue")
        self.assertEqual(
            authors[1]["raw_affiliations"],
            ["Michigan Tech. University"],
        )

    def test_parse_authors_multi_affil(self):
        author_str = (
            "Minglei Zhou, SKLP, Institute of Computing Technology; "
            "University of Chinese Academy of Sciences; "
            "Fei Wang, Shandong University"
        )
        authors = parse_authors(author_str)
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0]["author_name"], "Minglei Zhou")
        self.assertEqual(
            authors[0]["raw_affiliations"],
            [
                "SKLP, Institute of Computing Technology",
                "University of Chinese Academy of Sciences",
            ],
        )
        self.assertEqual(authors[1]["author_name"], "Fei Wang")
        self.assertEqual(authors[1]["raw_affiliations"], ["Shandong University"])

    def test_parse_program_text(self):
        sample = """
Session Type: Research Manuscript
Topic Area(s): AI
Room: Mtg Room 101B
• Fusedot: A Multiplication-Fused Dot Product Accelerator
  o Wenju Zhao, HUST; Jianhui Yue, MTU
• TDH-GNN: An Efficient Topology-Driven Accelerator
  o Hui Yu, HKUST; Wei Zhang, HKUST

Session Type: Exhibitor Forum
• Exhibitor Talk Title
  o Speaker Name, Company
"""
        papers = parse_program_text(sample)
        self.assertEqual(len(papers), 2)
        self.assertEqual(
            papers[0]["title"],
            "Fusedot: A Multiplication-Fused Dot Product Accelerator",
        )
        self.assertEqual(len(papers[0]["authors"]), 2)
        self.assertEqual(
            papers[1]["title"],
            "TDH-GNN: An Efficient Topology-Driven Accelerator",
        )

    def test_merge_program_papers(self):
        existing = [
            {
                "doi": "10.1145/3770743.1",
                "title": "Fusedot: A Multiplication-Fused Dot Product Accelerator",
                "source": "crossref",
            }
        ]
        program_papers = [
            {
                "title": "Fusedot: A Multiplication-Fused Dot Product Accelerator",
                "norm_title": "fusedot a multiplication fused dot product accelerator",
                "authors": [{"author_name": "Wenju Zhao", "raw_affiliations": ["HUST"]}],
            },
            {
                "title": "MASQ: Accelerating Masked Diffusion",
                "norm_title": "masq accelerating masked diffusion",
                "authors": [{"author_name": "Seeyeon Kim", "raw_affiliations": ["KAIST"]}],
            },
        ]

        merged, matched, added = merge_program_papers(existing, program_papers)
        self.assertEqual(matched, 1)
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["source"], "crossref")
        self.assertEqual(merged[0]["doi"], "10.1145/3770743.1")
        self.assertEqual(merged[1]["source"], "dac-program")
        self.assertEqual(merged[1]["title"], "MASQ: Accelerating Masked Diffusion")


if __name__ == "__main__":
    unittest.main()
