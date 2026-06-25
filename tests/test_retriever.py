import unittest

from esg_selective_mineru.retriever import HybridRetriever, LocalVectorRetriever, SimpleRetriever


class RetrieverTests(unittest.TestCase):
    def test_hybrid_retriever_keeps_bm25_exact_match_first(self):
        chunks = [
            {"chunk_id": "a", "page": 1, "text": "温室气体排放总量 1000 吨二氧化碳当量"},
            {"chunk_id": "b", "page": 2, "text": "员工培训覆盖率 98%"},
        ]
        field = {
            "field_key": "ghg_total",
            "name_cn": "温室气体排放总量",
            "aliases": ["GHG emissions"],
        }

        results = HybridRetriever(chunks).search_field(field, top_k=2)

        self.assertEqual(results[0]["chunk_id"], "a")
        self.assertIn("bm25", results[0]["retrieval_source"])

    def test_local_vector_retriever_recalls_partial_english_variant(self):
        chunks = [
            {"chunk_id": "a", "page": 1, "text": "The company discloses total GHG emissions by scope."},
            {"chunk_id": "b", "page": 2, "text": "Board independence and governance structure."},
        ]

        bm25_results = SimpleRetriever(chunks).search("greenhouse gas emissions", top_k=2)
        vector_results = LocalVectorRetriever(chunks).search("greenhouse gas emissions", top_k=2)

        self.assertEqual([item["chunk_id"] for item in bm25_results], ["a"])
        self.assertEqual(vector_results[0]["chunk_id"], "a")

    def test_hybrid_result_marks_retrieval_source(self):
        chunks = [
            {"chunk_id": "a", "page": 1, "text": "Scope 1 direct emissions reached 123 tCO2e."},
            {"chunk_id": "b", "page": 2, "text": "Customer satisfaction survey results."},
        ]

        results = HybridRetriever(chunks, bm25_top_k=1, vector_top_k=2).search("direct emission", top_k=2)

        self.assertEqual(results[0]["chunk_id"], "a")
        self.assertTrue(results[0]["retrieval_source"])


if __name__ == "__main__":
    unittest.main()
