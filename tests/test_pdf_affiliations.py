import unittest

from pipeline import pdf_affiliations as pa

COLUMNS = """Published as a conference paper at ICLR 2025

T ITLE OF A PAPER

 Rong Tang                                     Lizhen Lin& Yun Yang
 The Hong Kong University of Science and Technology   University of Maryland, College Park
 martang@ust.hk                                {lizhen01,yy84}@umd.edu


                                            A BSTRACT
"""

MARKERS = """Published as a conference paper at ICLR 2025

        T HERMAL G AUSSIAN
Rongfeng Lu1,3,∗,† Hangyu Chen1,∗ Ming Lu2 Le Zhang1 Bo Han1
         1
           Hangzhou Dianzi University 2 Intel Labs China 3 Lishui Institute of Hangzhou Dianzi University




            (a) RGB GT       (b) Thermal GT
        Figure 1: Compared to NeRF-based methods our approach improves quality.

                                                     A BSTRACT
"""

SYMBOL_MARKS = """C ODE MMLU

 Dung Nguyen Manh†∗, Nam Le Hai‡ , Quang Pham♢†
 †
   FPT Software AI Center, Viet Nam,
 ‡
   Hanoi University of Science and Technology,
 ♢
   Independent Researcher

                                              A BSTRACT
"""


ARROW_MARK = """M EMORY M OSAICS

    Jianyu Zhang† ↿ , Niklas Nolte† , Ranajoy Sadhukhan‡ , Léon Bottou† ↿
    †
      FAIR, Meta ‡ Carnegie Mellon University ↿ New York University


                                              A BSTRACT
"""

DOUBLE_DAGGER = """PSA

 Anmol Goel† , Amartya Sanyal††
 †
   Ubiquitous Knowledge Processing Lab (UKP Lab), Technical University of Darmstadt
 www.ukp.tu-darmstadt.de
 ††
   Department of Computer Science, University of Copenhagen, Denmark


                                              A BSTRACT
"""


class Extract(unittest.TestCase):
    def test_arrow_mark_is_a_mark(self):
        r = pa.extract(ARROW_MARK, ["Jianyu Zhang", "Niklas Nolte", "Ranajoy Sadhukhan", "Leon Bottou"])
        self.assertEqual(r["affiliations"][0], ["FAIR, Meta", "New York University"])
        self.assertEqual(r["affiliations"][2], ["Carnegie Mellon University"])
        self.assertEqual(r["affiliations"][3], ["FAIR, Meta", "New York University"])

    def test_doubled_dagger_is_distinct_from_dagger_and_urls_are_dropped(self):
        r = pa.extract(DOUBLE_DAGGER, ["Anmol Goel", "Amartya Sanyal"])
        self.assertEqual(r["affiliations"][1], ["Department of Computer Science, University of Copenhagen, Denmark"])
        self.assertEqual(r["affiliations"][0], ["Ubiquitous Knowledge Processing Lab (UKP Lab), Technical University of Darmstadt"])

    def test_columns_with_shared_block(self):
        r = pa.extract(COLUMNS, ["Rong Tang", "Lizhen Lin", "Yun Yang"])
        self.assertEqual(r["layout"], "columns")
        self.assertEqual(r["affiliations"][0], ["The Hong Kong University of Science and Technology"])
        self.assertEqual(r["affiliations"][1], ["University of Maryland, College Park"])
        self.assertEqual(r["affiliations"][2], ["University of Maryland, College Park"])
        self.assertEqual(r["confidence"], "high")

    def test_numeric_marks_glued_to_names_and_caption_not_absorbed(self):
        r = pa.extract(MARKERS, ["Rongfeng Lu", "Hangyu Chen", "Ming Lu", "Le Zhang", "Bo Han"])
        self.assertEqual(r["layout"], "markers")
        self.assertEqual(r["affiliations"][0], ["Hangzhou Dianzi University", "Lishui Institute of Hangzhou Dianzi University"])
        self.assertEqual(r["affiliations"][2], ["Intel Labs China"])
        self.assertNotIn("Figure", " ".join(sum(r["affiliations"], [])))
        self.assertEqual(r["confidence"], "high")

    def test_symbol_marks_and_extra_pdf_name_tokens(self):
        r = pa.extract(SYMBOL_MARKS, ["Dung Nguyen", "Nam Le Hai", "Quang Pham"])
        self.assertEqual(r["affiliations"][0], ["FPT Software AI Center, Viet Nam"])
        self.assertEqual(r["affiliations"][1], ["Hanoi University of Science and Technology"])
        self.assertEqual(r["affiliations"][2], ["Independent Researcher", "FPT Software AI Center, Viet Nam"])

    def test_missing_abstract_or_author_is_not_high_confidence(self):
        self.assertEqual(pa.extract("no abstract here", ["A B"])["confidence"], "none")
        r = pa.extract(COLUMNS, ["Rong Tang", "Somebody Else"])
        self.assertNotEqual(r["confidence"], "high")

    def test_dangling_marks_are_stripped(self):
        self.assertEqual(pa._clean_affiliation("University of Science and Technology of China 1 3"),
                         "University of Science and Technology of China")


if __name__ == "__main__":
    unittest.main()
