"""Standard-library checks of the static partition proof; no C is compiled."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parallel_kernels import prove,wrap

KEY="a"*64
SOURCE=f"""typedef __fp16 __fp164 __attribute__((aligned(8),ext_vector_type(4)));
void op_{KEY}(__fp16* restrict data0_32768, __fp16* restrict data1_32768) {{
  for (int Lidx0 = 0; Lidx0 < 8; Lidx0++) {{
    for (int Lidx1 = 0; Lidx1 < 1024; Lidx1++) {{
      int alu0 = ((Lidx0*4096)+(Lidx1<<2));
      *((__fp164*)((data0_32768+alu0))) = *((__fp164*)((data1_32768+alu0)));
    }}
  }}
}}
"""


class PartitionProofTest(unittest.TestCase):
    def test_independent_bounded_regions(self):
        result=prove(SOURCE)
        self.assertEqual(result[3],[(i*4096,(i+1)*4096) for i in range(8)])

    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):prove(SOURCE.replace('Lidx0*4096','Lidx0*2048'))

    def test_out_of_bounds_rejected(self):
        with self.assertRaises(ValueError):prove(SOURCE.replace('+(Lidx1<<2)','+(Lidx1<<2)+1'))

    def test_output_read_rejected(self):
        bad=SOURCE.replace('= *((__fp164*)((data1_32768+alu0)))','= *((__fp164*)((data0_32768+alu0)))')
        with self.assertRaises(ValueError):prove(bad)

    def test_unknown_index_rejected(self):
        with self.assertRaises((ValueError,KeyError)):prove(SOURCE.replace('Lidx0*4096','external_index*4096'))

    def test_alias_fallback_and_fast_contract(self):
        result=wrap(SOURCE,prove(SOURCE))
        self.assertIn(f'static void serial_{KEY}(__fp16* restrict data0_32768',result)
        self.assertIn(f'static void fallback_{KEY}(__fp16* data0_32768',result)
        self.assertIn('op_parallel_fallback(); fallback_',result)
        self.assertIn('sizeof(__fp16)*32768ul',result)
        self.assertIn('int Lidx0 = op_begin; Lidx0 < op_end;',result)


if __name__=='__main__':unittest.main()
