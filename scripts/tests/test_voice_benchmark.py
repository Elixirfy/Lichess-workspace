import unittest

from scripts.voice_benchmark import accuracy, latency, normalize, word_errors


class VoiceBenchmarkTest(unittest.TestCase):
    def test_normalization_keeps_wrong_rank_and_negation_visible(self):
        self.assertEqual(normalize("  MÃ,  ÉP BA!  "), "mã ép ba")
        self.assertEqual(normalize("F2-F4.", canonical=True), "ép hai ép bốn")
        self.assertEqual(
            normalize("không đi F2F3", canonical=True), "không đi ép hai ép ba"
        )
        self.assertNotEqual(normalize("ép hai ép ba", canonical=True), "ép hai ép bốn")
        self.assertEqual(normalize("24", canonical=True), "24")

    def test_word_error_counts_substitutions_insertions_and_deletions(self):
        self.assertEqual(word_errors("ép hai ép bốn", "ép hai ép ba"), 1)
        self.assertEqual(word_errors("mã ép ba", "mã ép"), 1)
        self.assertEqual(word_errors("bốn", "bốn bốn"), 1)
        self.assertEqual(word_errors("", "mã ép ba"), 3)

    def test_corpus_wer_uses_total_words_and_does_not_hide_number_formatting(self):
        rows = [("bốn", "ba"), ("mã ép ba", "mã ép")]
        self.assertEqual(accuracy(rows)["wer"], 0.5)
        self.assertEqual(accuracy(rows)["exact"], 0)
        self.assertEqual(accuracy([("ép hai ép bốn", "F2F4")])["exact"], 0)
        self.assertEqual(
            accuracy([("ép hai ép bốn", "F2F4")], canonical=True)["exact"], 1
        )

    def test_latency_reports_milliseconds_and_duration_relative_cost(self):
        result = latency(
            [{"total_s": 0.2, "duration_s": 2}, {"total_s": 1.0, "duration_s": 2}]
        )
        self.assertAlmostEqual(result["median_ms"], 600)
        self.assertAlmostEqual(result["p95_ms"], 960)
        self.assertAlmostEqual(result["rtf"], 0.3)


if __name__ == "__main__":
    unittest.main()
