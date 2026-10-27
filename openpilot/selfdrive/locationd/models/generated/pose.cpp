#include "pose.h"

namespace {
#define DIM 18
#define EDIM 18
#define MEDIM 18
typedef void (*Hfun)(double *, double *, double *);
const static double MAHA_THRESH_4 = 7.814727903251177;
const static double MAHA_THRESH_10 = 7.814727903251177;
const static double MAHA_THRESH_13 = 7.814727903251177;
const static double MAHA_THRESH_14 = 7.814727903251177;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_7465916839184854202) {
   out_7465916839184854202[0] = delta_x[0] + nom_x[0];
   out_7465916839184854202[1] = delta_x[1] + nom_x[1];
   out_7465916839184854202[2] = delta_x[2] + nom_x[2];
   out_7465916839184854202[3] = delta_x[3] + nom_x[3];
   out_7465916839184854202[4] = delta_x[4] + nom_x[4];
   out_7465916839184854202[5] = delta_x[5] + nom_x[5];
   out_7465916839184854202[6] = delta_x[6] + nom_x[6];
   out_7465916839184854202[7] = delta_x[7] + nom_x[7];
   out_7465916839184854202[8] = delta_x[8] + nom_x[8];
   out_7465916839184854202[9] = delta_x[9] + nom_x[9];
   out_7465916839184854202[10] = delta_x[10] + nom_x[10];
   out_7465916839184854202[11] = delta_x[11] + nom_x[11];
   out_7465916839184854202[12] = delta_x[12] + nom_x[12];
   out_7465916839184854202[13] = delta_x[13] + nom_x[13];
   out_7465916839184854202[14] = delta_x[14] + nom_x[14];
   out_7465916839184854202[15] = delta_x[15] + nom_x[15];
   out_7465916839184854202[16] = delta_x[16] + nom_x[16];
   out_7465916839184854202[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_1310847904861873779) {
   out_1310847904861873779[0] = -nom_x[0] + true_x[0];
   out_1310847904861873779[1] = -nom_x[1] + true_x[1];
   out_1310847904861873779[2] = -nom_x[2] + true_x[2];
   out_1310847904861873779[3] = -nom_x[3] + true_x[3];
   out_1310847904861873779[4] = -nom_x[4] + true_x[4];
   out_1310847904861873779[5] = -nom_x[5] + true_x[5];
   out_1310847904861873779[6] = -nom_x[6] + true_x[6];
   out_1310847904861873779[7] = -nom_x[7] + true_x[7];
   out_1310847904861873779[8] = -nom_x[8] + true_x[8];
   out_1310847904861873779[9] = -nom_x[9] + true_x[9];
   out_1310847904861873779[10] = -nom_x[10] + true_x[10];
   out_1310847904861873779[11] = -nom_x[11] + true_x[11];
   out_1310847904861873779[12] = -nom_x[12] + true_x[12];
   out_1310847904861873779[13] = -nom_x[13] + true_x[13];
   out_1310847904861873779[14] = -nom_x[14] + true_x[14];
   out_1310847904861873779[15] = -nom_x[15] + true_x[15];
   out_1310847904861873779[16] = -nom_x[16] + true_x[16];
   out_1310847904861873779[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_6607805894218821441) {
   out_6607805894218821441[0] = 1.0;
   out_6607805894218821441[1] = 0.0;
   out_6607805894218821441[2] = 0.0;
   out_6607805894218821441[3] = 0.0;
   out_6607805894218821441[4] = 0.0;
   out_6607805894218821441[5] = 0.0;
   out_6607805894218821441[6] = 0.0;
   out_6607805894218821441[7] = 0.0;
   out_6607805894218821441[8] = 0.0;
   out_6607805894218821441[9] = 0.0;
   out_6607805894218821441[10] = 0.0;
   out_6607805894218821441[11] = 0.0;
   out_6607805894218821441[12] = 0.0;
   out_6607805894218821441[13] = 0.0;
   out_6607805894218821441[14] = 0.0;
   out_6607805894218821441[15] = 0.0;
   out_6607805894218821441[16] = 0.0;
   out_6607805894218821441[17] = 0.0;
   out_6607805894218821441[18] = 0.0;
   out_6607805894218821441[19] = 1.0;
   out_6607805894218821441[20] = 0.0;
   out_6607805894218821441[21] = 0.0;
   out_6607805894218821441[22] = 0.0;
   out_6607805894218821441[23] = 0.0;
   out_6607805894218821441[24] = 0.0;
   out_6607805894218821441[25] = 0.0;
   out_6607805894218821441[26] = 0.0;
   out_6607805894218821441[27] = 0.0;
   out_6607805894218821441[28] = 0.0;
   out_6607805894218821441[29] = 0.0;
   out_6607805894218821441[30] = 0.0;
   out_6607805894218821441[31] = 0.0;
   out_6607805894218821441[32] = 0.0;
   out_6607805894218821441[33] = 0.0;
   out_6607805894218821441[34] = 0.0;
   out_6607805894218821441[35] = 0.0;
   out_6607805894218821441[36] = 0.0;
   out_6607805894218821441[37] = 0.0;
   out_6607805894218821441[38] = 1.0;
   out_6607805894218821441[39] = 0.0;
   out_6607805894218821441[40] = 0.0;
   out_6607805894218821441[41] = 0.0;
   out_6607805894218821441[42] = 0.0;
   out_6607805894218821441[43] = 0.0;
   out_6607805894218821441[44] = 0.0;
   out_6607805894218821441[45] = 0.0;
   out_6607805894218821441[46] = 0.0;
   out_6607805894218821441[47] = 0.0;
   out_6607805894218821441[48] = 0.0;
   out_6607805894218821441[49] = 0.0;
   out_6607805894218821441[50] = 0.0;
   out_6607805894218821441[51] = 0.0;
   out_6607805894218821441[52] = 0.0;
   out_6607805894218821441[53] = 0.0;
   out_6607805894218821441[54] = 0.0;
   out_6607805894218821441[55] = 0.0;
   out_6607805894218821441[56] = 0.0;
   out_6607805894218821441[57] = 1.0;
   out_6607805894218821441[58] = 0.0;
   out_6607805894218821441[59] = 0.0;
   out_6607805894218821441[60] = 0.0;
   out_6607805894218821441[61] = 0.0;
   out_6607805894218821441[62] = 0.0;
   out_6607805894218821441[63] = 0.0;
   out_6607805894218821441[64] = 0.0;
   out_6607805894218821441[65] = 0.0;
   out_6607805894218821441[66] = 0.0;
   out_6607805894218821441[67] = 0.0;
   out_6607805894218821441[68] = 0.0;
   out_6607805894218821441[69] = 0.0;
   out_6607805894218821441[70] = 0.0;
   out_6607805894218821441[71] = 0.0;
   out_6607805894218821441[72] = 0.0;
   out_6607805894218821441[73] = 0.0;
   out_6607805894218821441[74] = 0.0;
   out_6607805894218821441[75] = 0.0;
   out_6607805894218821441[76] = 1.0;
   out_6607805894218821441[77] = 0.0;
   out_6607805894218821441[78] = 0.0;
   out_6607805894218821441[79] = 0.0;
   out_6607805894218821441[80] = 0.0;
   out_6607805894218821441[81] = 0.0;
   out_6607805894218821441[82] = 0.0;
   out_6607805894218821441[83] = 0.0;
   out_6607805894218821441[84] = 0.0;
   out_6607805894218821441[85] = 0.0;
   out_6607805894218821441[86] = 0.0;
   out_6607805894218821441[87] = 0.0;
   out_6607805894218821441[88] = 0.0;
   out_6607805894218821441[89] = 0.0;
   out_6607805894218821441[90] = 0.0;
   out_6607805894218821441[91] = 0.0;
   out_6607805894218821441[92] = 0.0;
   out_6607805894218821441[93] = 0.0;
   out_6607805894218821441[94] = 0.0;
   out_6607805894218821441[95] = 1.0;
   out_6607805894218821441[96] = 0.0;
   out_6607805894218821441[97] = 0.0;
   out_6607805894218821441[98] = 0.0;
   out_6607805894218821441[99] = 0.0;
   out_6607805894218821441[100] = 0.0;
   out_6607805894218821441[101] = 0.0;
   out_6607805894218821441[102] = 0.0;
   out_6607805894218821441[103] = 0.0;
   out_6607805894218821441[104] = 0.0;
   out_6607805894218821441[105] = 0.0;
   out_6607805894218821441[106] = 0.0;
   out_6607805894218821441[107] = 0.0;
   out_6607805894218821441[108] = 0.0;
   out_6607805894218821441[109] = 0.0;
   out_6607805894218821441[110] = 0.0;
   out_6607805894218821441[111] = 0.0;
   out_6607805894218821441[112] = 0.0;
   out_6607805894218821441[113] = 0.0;
   out_6607805894218821441[114] = 1.0;
   out_6607805894218821441[115] = 0.0;
   out_6607805894218821441[116] = 0.0;
   out_6607805894218821441[117] = 0.0;
   out_6607805894218821441[118] = 0.0;
   out_6607805894218821441[119] = 0.0;
   out_6607805894218821441[120] = 0.0;
   out_6607805894218821441[121] = 0.0;
   out_6607805894218821441[122] = 0.0;
   out_6607805894218821441[123] = 0.0;
   out_6607805894218821441[124] = 0.0;
   out_6607805894218821441[125] = 0.0;
   out_6607805894218821441[126] = 0.0;
   out_6607805894218821441[127] = 0.0;
   out_6607805894218821441[128] = 0.0;
   out_6607805894218821441[129] = 0.0;
   out_6607805894218821441[130] = 0.0;
   out_6607805894218821441[131] = 0.0;
   out_6607805894218821441[132] = 0.0;
   out_6607805894218821441[133] = 1.0;
   out_6607805894218821441[134] = 0.0;
   out_6607805894218821441[135] = 0.0;
   out_6607805894218821441[136] = 0.0;
   out_6607805894218821441[137] = 0.0;
   out_6607805894218821441[138] = 0.0;
   out_6607805894218821441[139] = 0.0;
   out_6607805894218821441[140] = 0.0;
   out_6607805894218821441[141] = 0.0;
   out_6607805894218821441[142] = 0.0;
   out_6607805894218821441[143] = 0.0;
   out_6607805894218821441[144] = 0.0;
   out_6607805894218821441[145] = 0.0;
   out_6607805894218821441[146] = 0.0;
   out_6607805894218821441[147] = 0.0;
   out_6607805894218821441[148] = 0.0;
   out_6607805894218821441[149] = 0.0;
   out_6607805894218821441[150] = 0.0;
   out_6607805894218821441[151] = 0.0;
   out_6607805894218821441[152] = 1.0;
   out_6607805894218821441[153] = 0.0;
   out_6607805894218821441[154] = 0.0;
   out_6607805894218821441[155] = 0.0;
   out_6607805894218821441[156] = 0.0;
   out_6607805894218821441[157] = 0.0;
   out_6607805894218821441[158] = 0.0;
   out_6607805894218821441[159] = 0.0;
   out_6607805894218821441[160] = 0.0;
   out_6607805894218821441[161] = 0.0;
   out_6607805894218821441[162] = 0.0;
   out_6607805894218821441[163] = 0.0;
   out_6607805894218821441[164] = 0.0;
   out_6607805894218821441[165] = 0.0;
   out_6607805894218821441[166] = 0.0;
   out_6607805894218821441[167] = 0.0;
   out_6607805894218821441[168] = 0.0;
   out_6607805894218821441[169] = 0.0;
   out_6607805894218821441[170] = 0.0;
   out_6607805894218821441[171] = 1.0;
   out_6607805894218821441[172] = 0.0;
   out_6607805894218821441[173] = 0.0;
   out_6607805894218821441[174] = 0.0;
   out_6607805894218821441[175] = 0.0;
   out_6607805894218821441[176] = 0.0;
   out_6607805894218821441[177] = 0.0;
   out_6607805894218821441[178] = 0.0;
   out_6607805894218821441[179] = 0.0;
   out_6607805894218821441[180] = 0.0;
   out_6607805894218821441[181] = 0.0;
   out_6607805894218821441[182] = 0.0;
   out_6607805894218821441[183] = 0.0;
   out_6607805894218821441[184] = 0.0;
   out_6607805894218821441[185] = 0.0;
   out_6607805894218821441[186] = 0.0;
   out_6607805894218821441[187] = 0.0;
   out_6607805894218821441[188] = 0.0;
   out_6607805894218821441[189] = 0.0;
   out_6607805894218821441[190] = 1.0;
   out_6607805894218821441[191] = 0.0;
   out_6607805894218821441[192] = 0.0;
   out_6607805894218821441[193] = 0.0;
   out_6607805894218821441[194] = 0.0;
   out_6607805894218821441[195] = 0.0;
   out_6607805894218821441[196] = 0.0;
   out_6607805894218821441[197] = 0.0;
   out_6607805894218821441[198] = 0.0;
   out_6607805894218821441[199] = 0.0;
   out_6607805894218821441[200] = 0.0;
   out_6607805894218821441[201] = 0.0;
   out_6607805894218821441[202] = 0.0;
   out_6607805894218821441[203] = 0.0;
   out_6607805894218821441[204] = 0.0;
   out_6607805894218821441[205] = 0.0;
   out_6607805894218821441[206] = 0.0;
   out_6607805894218821441[207] = 0.0;
   out_6607805894218821441[208] = 0.0;
   out_6607805894218821441[209] = 1.0;
   out_6607805894218821441[210] = 0.0;
   out_6607805894218821441[211] = 0.0;
   out_6607805894218821441[212] = 0.0;
   out_6607805894218821441[213] = 0.0;
   out_6607805894218821441[214] = 0.0;
   out_6607805894218821441[215] = 0.0;
   out_6607805894218821441[216] = 0.0;
   out_6607805894218821441[217] = 0.0;
   out_6607805894218821441[218] = 0.0;
   out_6607805894218821441[219] = 0.0;
   out_6607805894218821441[220] = 0.0;
   out_6607805894218821441[221] = 0.0;
   out_6607805894218821441[222] = 0.0;
   out_6607805894218821441[223] = 0.0;
   out_6607805894218821441[224] = 0.0;
   out_6607805894218821441[225] = 0.0;
   out_6607805894218821441[226] = 0.0;
   out_6607805894218821441[227] = 0.0;
   out_6607805894218821441[228] = 1.0;
   out_6607805894218821441[229] = 0.0;
   out_6607805894218821441[230] = 0.0;
   out_6607805894218821441[231] = 0.0;
   out_6607805894218821441[232] = 0.0;
   out_6607805894218821441[233] = 0.0;
   out_6607805894218821441[234] = 0.0;
   out_6607805894218821441[235] = 0.0;
   out_6607805894218821441[236] = 0.0;
   out_6607805894218821441[237] = 0.0;
   out_6607805894218821441[238] = 0.0;
   out_6607805894218821441[239] = 0.0;
   out_6607805894218821441[240] = 0.0;
   out_6607805894218821441[241] = 0.0;
   out_6607805894218821441[242] = 0.0;
   out_6607805894218821441[243] = 0.0;
   out_6607805894218821441[244] = 0.0;
   out_6607805894218821441[245] = 0.0;
   out_6607805894218821441[246] = 0.0;
   out_6607805894218821441[247] = 1.0;
   out_6607805894218821441[248] = 0.0;
   out_6607805894218821441[249] = 0.0;
   out_6607805894218821441[250] = 0.0;
   out_6607805894218821441[251] = 0.0;
   out_6607805894218821441[252] = 0.0;
   out_6607805894218821441[253] = 0.0;
   out_6607805894218821441[254] = 0.0;
   out_6607805894218821441[255] = 0.0;
   out_6607805894218821441[256] = 0.0;
   out_6607805894218821441[257] = 0.0;
   out_6607805894218821441[258] = 0.0;
   out_6607805894218821441[259] = 0.0;
   out_6607805894218821441[260] = 0.0;
   out_6607805894218821441[261] = 0.0;
   out_6607805894218821441[262] = 0.0;
   out_6607805894218821441[263] = 0.0;
   out_6607805894218821441[264] = 0.0;
   out_6607805894218821441[265] = 0.0;
   out_6607805894218821441[266] = 1.0;
   out_6607805894218821441[267] = 0.0;
   out_6607805894218821441[268] = 0.0;
   out_6607805894218821441[269] = 0.0;
   out_6607805894218821441[270] = 0.0;
   out_6607805894218821441[271] = 0.0;
   out_6607805894218821441[272] = 0.0;
   out_6607805894218821441[273] = 0.0;
   out_6607805894218821441[274] = 0.0;
   out_6607805894218821441[275] = 0.0;
   out_6607805894218821441[276] = 0.0;
   out_6607805894218821441[277] = 0.0;
   out_6607805894218821441[278] = 0.0;
   out_6607805894218821441[279] = 0.0;
   out_6607805894218821441[280] = 0.0;
   out_6607805894218821441[281] = 0.0;
   out_6607805894218821441[282] = 0.0;
   out_6607805894218821441[283] = 0.0;
   out_6607805894218821441[284] = 0.0;
   out_6607805894218821441[285] = 1.0;
   out_6607805894218821441[286] = 0.0;
   out_6607805894218821441[287] = 0.0;
   out_6607805894218821441[288] = 0.0;
   out_6607805894218821441[289] = 0.0;
   out_6607805894218821441[290] = 0.0;
   out_6607805894218821441[291] = 0.0;
   out_6607805894218821441[292] = 0.0;
   out_6607805894218821441[293] = 0.0;
   out_6607805894218821441[294] = 0.0;
   out_6607805894218821441[295] = 0.0;
   out_6607805894218821441[296] = 0.0;
   out_6607805894218821441[297] = 0.0;
   out_6607805894218821441[298] = 0.0;
   out_6607805894218821441[299] = 0.0;
   out_6607805894218821441[300] = 0.0;
   out_6607805894218821441[301] = 0.0;
   out_6607805894218821441[302] = 0.0;
   out_6607805894218821441[303] = 0.0;
   out_6607805894218821441[304] = 1.0;
   out_6607805894218821441[305] = 0.0;
   out_6607805894218821441[306] = 0.0;
   out_6607805894218821441[307] = 0.0;
   out_6607805894218821441[308] = 0.0;
   out_6607805894218821441[309] = 0.0;
   out_6607805894218821441[310] = 0.0;
   out_6607805894218821441[311] = 0.0;
   out_6607805894218821441[312] = 0.0;
   out_6607805894218821441[313] = 0.0;
   out_6607805894218821441[314] = 0.0;
   out_6607805894218821441[315] = 0.0;
   out_6607805894218821441[316] = 0.0;
   out_6607805894218821441[317] = 0.0;
   out_6607805894218821441[318] = 0.0;
   out_6607805894218821441[319] = 0.0;
   out_6607805894218821441[320] = 0.0;
   out_6607805894218821441[321] = 0.0;
   out_6607805894218821441[322] = 0.0;
   out_6607805894218821441[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_534660845839446436) {
   out_534660845839446436[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_534660845839446436[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_534660845839446436[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_534660845839446436[3] = dt*state[12] + state[3];
   out_534660845839446436[4] = dt*state[13] + state[4];
   out_534660845839446436[5] = dt*state[14] + state[5];
   out_534660845839446436[6] = state[6];
   out_534660845839446436[7] = state[7];
   out_534660845839446436[8] = state[8];
   out_534660845839446436[9] = state[9];
   out_534660845839446436[10] = state[10];
   out_534660845839446436[11] = state[11];
   out_534660845839446436[12] = state[12];
   out_534660845839446436[13] = state[13];
   out_534660845839446436[14] = state[14];
   out_534660845839446436[15] = state[15];
   out_534660845839446436[16] = state[16];
   out_534660845839446436[17] = state[17];
}
void F_fun(double *state, double dt, double *out_384983850267682172) {
   out_384983850267682172[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_384983850267682172[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_384983850267682172[2] = 0;
   out_384983850267682172[3] = 0;
   out_384983850267682172[4] = 0;
   out_384983850267682172[5] = 0;
   out_384983850267682172[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_384983850267682172[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_384983850267682172[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_384983850267682172[9] = 0;
   out_384983850267682172[10] = 0;
   out_384983850267682172[11] = 0;
   out_384983850267682172[12] = 0;
   out_384983850267682172[13] = 0;
   out_384983850267682172[14] = 0;
   out_384983850267682172[15] = 0;
   out_384983850267682172[16] = 0;
   out_384983850267682172[17] = 0;
   out_384983850267682172[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_384983850267682172[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_384983850267682172[20] = 0;
   out_384983850267682172[21] = 0;
   out_384983850267682172[22] = 0;
   out_384983850267682172[23] = 0;
   out_384983850267682172[24] = 0;
   out_384983850267682172[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_384983850267682172[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_384983850267682172[27] = 0;
   out_384983850267682172[28] = 0;
   out_384983850267682172[29] = 0;
   out_384983850267682172[30] = 0;
   out_384983850267682172[31] = 0;
   out_384983850267682172[32] = 0;
   out_384983850267682172[33] = 0;
   out_384983850267682172[34] = 0;
   out_384983850267682172[35] = 0;
   out_384983850267682172[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_384983850267682172[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_384983850267682172[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_384983850267682172[39] = 0;
   out_384983850267682172[40] = 0;
   out_384983850267682172[41] = 0;
   out_384983850267682172[42] = 0;
   out_384983850267682172[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_384983850267682172[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_384983850267682172[45] = 0;
   out_384983850267682172[46] = 0;
   out_384983850267682172[47] = 0;
   out_384983850267682172[48] = 0;
   out_384983850267682172[49] = 0;
   out_384983850267682172[50] = 0;
   out_384983850267682172[51] = 0;
   out_384983850267682172[52] = 0;
   out_384983850267682172[53] = 0;
   out_384983850267682172[54] = 0;
   out_384983850267682172[55] = 0;
   out_384983850267682172[56] = 0;
   out_384983850267682172[57] = 1;
   out_384983850267682172[58] = 0;
   out_384983850267682172[59] = 0;
   out_384983850267682172[60] = 0;
   out_384983850267682172[61] = 0;
   out_384983850267682172[62] = 0;
   out_384983850267682172[63] = 0;
   out_384983850267682172[64] = 0;
   out_384983850267682172[65] = 0;
   out_384983850267682172[66] = dt;
   out_384983850267682172[67] = 0;
   out_384983850267682172[68] = 0;
   out_384983850267682172[69] = 0;
   out_384983850267682172[70] = 0;
   out_384983850267682172[71] = 0;
   out_384983850267682172[72] = 0;
   out_384983850267682172[73] = 0;
   out_384983850267682172[74] = 0;
   out_384983850267682172[75] = 0;
   out_384983850267682172[76] = 1;
   out_384983850267682172[77] = 0;
   out_384983850267682172[78] = 0;
   out_384983850267682172[79] = 0;
   out_384983850267682172[80] = 0;
   out_384983850267682172[81] = 0;
   out_384983850267682172[82] = 0;
   out_384983850267682172[83] = 0;
   out_384983850267682172[84] = 0;
   out_384983850267682172[85] = dt;
   out_384983850267682172[86] = 0;
   out_384983850267682172[87] = 0;
   out_384983850267682172[88] = 0;
   out_384983850267682172[89] = 0;
   out_384983850267682172[90] = 0;
   out_384983850267682172[91] = 0;
   out_384983850267682172[92] = 0;
   out_384983850267682172[93] = 0;
   out_384983850267682172[94] = 0;
   out_384983850267682172[95] = 1;
   out_384983850267682172[96] = 0;
   out_384983850267682172[97] = 0;
   out_384983850267682172[98] = 0;
   out_384983850267682172[99] = 0;
   out_384983850267682172[100] = 0;
   out_384983850267682172[101] = 0;
   out_384983850267682172[102] = 0;
   out_384983850267682172[103] = 0;
   out_384983850267682172[104] = dt;
   out_384983850267682172[105] = 0;
   out_384983850267682172[106] = 0;
   out_384983850267682172[107] = 0;
   out_384983850267682172[108] = 0;
   out_384983850267682172[109] = 0;
   out_384983850267682172[110] = 0;
   out_384983850267682172[111] = 0;
   out_384983850267682172[112] = 0;
   out_384983850267682172[113] = 0;
   out_384983850267682172[114] = 1;
   out_384983850267682172[115] = 0;
   out_384983850267682172[116] = 0;
   out_384983850267682172[117] = 0;
   out_384983850267682172[118] = 0;
   out_384983850267682172[119] = 0;
   out_384983850267682172[120] = 0;
   out_384983850267682172[121] = 0;
   out_384983850267682172[122] = 0;
   out_384983850267682172[123] = 0;
   out_384983850267682172[124] = 0;
   out_384983850267682172[125] = 0;
   out_384983850267682172[126] = 0;
   out_384983850267682172[127] = 0;
   out_384983850267682172[128] = 0;
   out_384983850267682172[129] = 0;
   out_384983850267682172[130] = 0;
   out_384983850267682172[131] = 0;
   out_384983850267682172[132] = 0;
   out_384983850267682172[133] = 1;
   out_384983850267682172[134] = 0;
   out_384983850267682172[135] = 0;
   out_384983850267682172[136] = 0;
   out_384983850267682172[137] = 0;
   out_384983850267682172[138] = 0;
   out_384983850267682172[139] = 0;
   out_384983850267682172[140] = 0;
   out_384983850267682172[141] = 0;
   out_384983850267682172[142] = 0;
   out_384983850267682172[143] = 0;
   out_384983850267682172[144] = 0;
   out_384983850267682172[145] = 0;
   out_384983850267682172[146] = 0;
   out_384983850267682172[147] = 0;
   out_384983850267682172[148] = 0;
   out_384983850267682172[149] = 0;
   out_384983850267682172[150] = 0;
   out_384983850267682172[151] = 0;
   out_384983850267682172[152] = 1;
   out_384983850267682172[153] = 0;
   out_384983850267682172[154] = 0;
   out_384983850267682172[155] = 0;
   out_384983850267682172[156] = 0;
   out_384983850267682172[157] = 0;
   out_384983850267682172[158] = 0;
   out_384983850267682172[159] = 0;
   out_384983850267682172[160] = 0;
   out_384983850267682172[161] = 0;
   out_384983850267682172[162] = 0;
   out_384983850267682172[163] = 0;
   out_384983850267682172[164] = 0;
   out_384983850267682172[165] = 0;
   out_384983850267682172[166] = 0;
   out_384983850267682172[167] = 0;
   out_384983850267682172[168] = 0;
   out_384983850267682172[169] = 0;
   out_384983850267682172[170] = 0;
   out_384983850267682172[171] = 1;
   out_384983850267682172[172] = 0;
   out_384983850267682172[173] = 0;
   out_384983850267682172[174] = 0;
   out_384983850267682172[175] = 0;
   out_384983850267682172[176] = 0;
   out_384983850267682172[177] = 0;
   out_384983850267682172[178] = 0;
   out_384983850267682172[179] = 0;
   out_384983850267682172[180] = 0;
   out_384983850267682172[181] = 0;
   out_384983850267682172[182] = 0;
   out_384983850267682172[183] = 0;
   out_384983850267682172[184] = 0;
   out_384983850267682172[185] = 0;
   out_384983850267682172[186] = 0;
   out_384983850267682172[187] = 0;
   out_384983850267682172[188] = 0;
   out_384983850267682172[189] = 0;
   out_384983850267682172[190] = 1;
   out_384983850267682172[191] = 0;
   out_384983850267682172[192] = 0;
   out_384983850267682172[193] = 0;
   out_384983850267682172[194] = 0;
   out_384983850267682172[195] = 0;
   out_384983850267682172[196] = 0;
   out_384983850267682172[197] = 0;
   out_384983850267682172[198] = 0;
   out_384983850267682172[199] = 0;
   out_384983850267682172[200] = 0;
   out_384983850267682172[201] = 0;
   out_384983850267682172[202] = 0;
   out_384983850267682172[203] = 0;
   out_384983850267682172[204] = 0;
   out_384983850267682172[205] = 0;
   out_384983850267682172[206] = 0;
   out_384983850267682172[207] = 0;
   out_384983850267682172[208] = 0;
   out_384983850267682172[209] = 1;
   out_384983850267682172[210] = 0;
   out_384983850267682172[211] = 0;
   out_384983850267682172[212] = 0;
   out_384983850267682172[213] = 0;
   out_384983850267682172[214] = 0;
   out_384983850267682172[215] = 0;
   out_384983850267682172[216] = 0;
   out_384983850267682172[217] = 0;
   out_384983850267682172[218] = 0;
   out_384983850267682172[219] = 0;
   out_384983850267682172[220] = 0;
   out_384983850267682172[221] = 0;
   out_384983850267682172[222] = 0;
   out_384983850267682172[223] = 0;
   out_384983850267682172[224] = 0;
   out_384983850267682172[225] = 0;
   out_384983850267682172[226] = 0;
   out_384983850267682172[227] = 0;
   out_384983850267682172[228] = 1;
   out_384983850267682172[229] = 0;
   out_384983850267682172[230] = 0;
   out_384983850267682172[231] = 0;
   out_384983850267682172[232] = 0;
   out_384983850267682172[233] = 0;
   out_384983850267682172[234] = 0;
   out_384983850267682172[235] = 0;
   out_384983850267682172[236] = 0;
   out_384983850267682172[237] = 0;
   out_384983850267682172[238] = 0;
   out_384983850267682172[239] = 0;
   out_384983850267682172[240] = 0;
   out_384983850267682172[241] = 0;
   out_384983850267682172[242] = 0;
   out_384983850267682172[243] = 0;
   out_384983850267682172[244] = 0;
   out_384983850267682172[245] = 0;
   out_384983850267682172[246] = 0;
   out_384983850267682172[247] = 1;
   out_384983850267682172[248] = 0;
   out_384983850267682172[249] = 0;
   out_384983850267682172[250] = 0;
   out_384983850267682172[251] = 0;
   out_384983850267682172[252] = 0;
   out_384983850267682172[253] = 0;
   out_384983850267682172[254] = 0;
   out_384983850267682172[255] = 0;
   out_384983850267682172[256] = 0;
   out_384983850267682172[257] = 0;
   out_384983850267682172[258] = 0;
   out_384983850267682172[259] = 0;
   out_384983850267682172[260] = 0;
   out_384983850267682172[261] = 0;
   out_384983850267682172[262] = 0;
   out_384983850267682172[263] = 0;
   out_384983850267682172[264] = 0;
   out_384983850267682172[265] = 0;
   out_384983850267682172[266] = 1;
   out_384983850267682172[267] = 0;
   out_384983850267682172[268] = 0;
   out_384983850267682172[269] = 0;
   out_384983850267682172[270] = 0;
   out_384983850267682172[271] = 0;
   out_384983850267682172[272] = 0;
   out_384983850267682172[273] = 0;
   out_384983850267682172[274] = 0;
   out_384983850267682172[275] = 0;
   out_384983850267682172[276] = 0;
   out_384983850267682172[277] = 0;
   out_384983850267682172[278] = 0;
   out_384983850267682172[279] = 0;
   out_384983850267682172[280] = 0;
   out_384983850267682172[281] = 0;
   out_384983850267682172[282] = 0;
   out_384983850267682172[283] = 0;
   out_384983850267682172[284] = 0;
   out_384983850267682172[285] = 1;
   out_384983850267682172[286] = 0;
   out_384983850267682172[287] = 0;
   out_384983850267682172[288] = 0;
   out_384983850267682172[289] = 0;
   out_384983850267682172[290] = 0;
   out_384983850267682172[291] = 0;
   out_384983850267682172[292] = 0;
   out_384983850267682172[293] = 0;
   out_384983850267682172[294] = 0;
   out_384983850267682172[295] = 0;
   out_384983850267682172[296] = 0;
   out_384983850267682172[297] = 0;
   out_384983850267682172[298] = 0;
   out_384983850267682172[299] = 0;
   out_384983850267682172[300] = 0;
   out_384983850267682172[301] = 0;
   out_384983850267682172[302] = 0;
   out_384983850267682172[303] = 0;
   out_384983850267682172[304] = 1;
   out_384983850267682172[305] = 0;
   out_384983850267682172[306] = 0;
   out_384983850267682172[307] = 0;
   out_384983850267682172[308] = 0;
   out_384983850267682172[309] = 0;
   out_384983850267682172[310] = 0;
   out_384983850267682172[311] = 0;
   out_384983850267682172[312] = 0;
   out_384983850267682172[313] = 0;
   out_384983850267682172[314] = 0;
   out_384983850267682172[315] = 0;
   out_384983850267682172[316] = 0;
   out_384983850267682172[317] = 0;
   out_384983850267682172[318] = 0;
   out_384983850267682172[319] = 0;
   out_384983850267682172[320] = 0;
   out_384983850267682172[321] = 0;
   out_384983850267682172[322] = 0;
   out_384983850267682172[323] = 1;
}
void h_4(double *state, double *unused, double *out_185862018060751764) {
   out_185862018060751764[0] = state[6] + state[9];
   out_185862018060751764[1] = state[7] + state[10];
   out_185862018060751764[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_9186464551296892708) {
   out_9186464551296892708[0] = 0;
   out_9186464551296892708[1] = 0;
   out_9186464551296892708[2] = 0;
   out_9186464551296892708[3] = 0;
   out_9186464551296892708[4] = 0;
   out_9186464551296892708[5] = 0;
   out_9186464551296892708[6] = 1;
   out_9186464551296892708[7] = 0;
   out_9186464551296892708[8] = 0;
   out_9186464551296892708[9] = 1;
   out_9186464551296892708[10] = 0;
   out_9186464551296892708[11] = 0;
   out_9186464551296892708[12] = 0;
   out_9186464551296892708[13] = 0;
   out_9186464551296892708[14] = 0;
   out_9186464551296892708[15] = 0;
   out_9186464551296892708[16] = 0;
   out_9186464551296892708[17] = 0;
   out_9186464551296892708[18] = 0;
   out_9186464551296892708[19] = 0;
   out_9186464551296892708[20] = 0;
   out_9186464551296892708[21] = 0;
   out_9186464551296892708[22] = 0;
   out_9186464551296892708[23] = 0;
   out_9186464551296892708[24] = 0;
   out_9186464551296892708[25] = 1;
   out_9186464551296892708[26] = 0;
   out_9186464551296892708[27] = 0;
   out_9186464551296892708[28] = 1;
   out_9186464551296892708[29] = 0;
   out_9186464551296892708[30] = 0;
   out_9186464551296892708[31] = 0;
   out_9186464551296892708[32] = 0;
   out_9186464551296892708[33] = 0;
   out_9186464551296892708[34] = 0;
   out_9186464551296892708[35] = 0;
   out_9186464551296892708[36] = 0;
   out_9186464551296892708[37] = 0;
   out_9186464551296892708[38] = 0;
   out_9186464551296892708[39] = 0;
   out_9186464551296892708[40] = 0;
   out_9186464551296892708[41] = 0;
   out_9186464551296892708[42] = 0;
   out_9186464551296892708[43] = 0;
   out_9186464551296892708[44] = 1;
   out_9186464551296892708[45] = 0;
   out_9186464551296892708[46] = 0;
   out_9186464551296892708[47] = 1;
   out_9186464551296892708[48] = 0;
   out_9186464551296892708[49] = 0;
   out_9186464551296892708[50] = 0;
   out_9186464551296892708[51] = 0;
   out_9186464551296892708[52] = 0;
   out_9186464551296892708[53] = 0;
}
void h_10(double *state, double *unused, double *out_4781947873589601556) {
   out_4781947873589601556[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_4781947873589601556[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_4781947873589601556[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_8921185053970104970) {
   out_8921185053970104970[0] = 0;
   out_8921185053970104970[1] = 9.8100000000000005*cos(state[1]);
   out_8921185053970104970[2] = 0;
   out_8921185053970104970[3] = 0;
   out_8921185053970104970[4] = -state[8];
   out_8921185053970104970[5] = state[7];
   out_8921185053970104970[6] = 0;
   out_8921185053970104970[7] = state[5];
   out_8921185053970104970[8] = -state[4];
   out_8921185053970104970[9] = 0;
   out_8921185053970104970[10] = 0;
   out_8921185053970104970[11] = 0;
   out_8921185053970104970[12] = 1;
   out_8921185053970104970[13] = 0;
   out_8921185053970104970[14] = 0;
   out_8921185053970104970[15] = 1;
   out_8921185053970104970[16] = 0;
   out_8921185053970104970[17] = 0;
   out_8921185053970104970[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_8921185053970104970[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_8921185053970104970[20] = 0;
   out_8921185053970104970[21] = state[8];
   out_8921185053970104970[22] = 0;
   out_8921185053970104970[23] = -state[6];
   out_8921185053970104970[24] = -state[5];
   out_8921185053970104970[25] = 0;
   out_8921185053970104970[26] = state[3];
   out_8921185053970104970[27] = 0;
   out_8921185053970104970[28] = 0;
   out_8921185053970104970[29] = 0;
   out_8921185053970104970[30] = 0;
   out_8921185053970104970[31] = 1;
   out_8921185053970104970[32] = 0;
   out_8921185053970104970[33] = 0;
   out_8921185053970104970[34] = 1;
   out_8921185053970104970[35] = 0;
   out_8921185053970104970[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_8921185053970104970[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_8921185053970104970[38] = 0;
   out_8921185053970104970[39] = -state[7];
   out_8921185053970104970[40] = state[6];
   out_8921185053970104970[41] = 0;
   out_8921185053970104970[42] = state[4];
   out_8921185053970104970[43] = -state[3];
   out_8921185053970104970[44] = 0;
   out_8921185053970104970[45] = 0;
   out_8921185053970104970[46] = 0;
   out_8921185053970104970[47] = 0;
   out_8921185053970104970[48] = 0;
   out_8921185053970104970[49] = 0;
   out_8921185053970104970[50] = 1;
   out_8921185053970104970[51] = 0;
   out_8921185053970104970[52] = 0;
   out_8921185053970104970[53] = 1;
}
void h_13(double *state, double *unused, double *out_4868669237854762150) {
   out_4868669237854762150[0] = state[3];
   out_4868669237854762150[1] = state[4];
   out_4868669237854762150[2] = state[5];
}
void H_13(double *state, double *unused, double *out_6048005697080326107) {
   out_6048005697080326107[0] = 0;
   out_6048005697080326107[1] = 0;
   out_6048005697080326107[2] = 0;
   out_6048005697080326107[3] = 1;
   out_6048005697080326107[4] = 0;
   out_6048005697080326107[5] = 0;
   out_6048005697080326107[6] = 0;
   out_6048005697080326107[7] = 0;
   out_6048005697080326107[8] = 0;
   out_6048005697080326107[9] = 0;
   out_6048005697080326107[10] = 0;
   out_6048005697080326107[11] = 0;
   out_6048005697080326107[12] = 0;
   out_6048005697080326107[13] = 0;
   out_6048005697080326107[14] = 0;
   out_6048005697080326107[15] = 0;
   out_6048005697080326107[16] = 0;
   out_6048005697080326107[17] = 0;
   out_6048005697080326107[18] = 0;
   out_6048005697080326107[19] = 0;
   out_6048005697080326107[20] = 0;
   out_6048005697080326107[21] = 0;
   out_6048005697080326107[22] = 1;
   out_6048005697080326107[23] = 0;
   out_6048005697080326107[24] = 0;
   out_6048005697080326107[25] = 0;
   out_6048005697080326107[26] = 0;
   out_6048005697080326107[27] = 0;
   out_6048005697080326107[28] = 0;
   out_6048005697080326107[29] = 0;
   out_6048005697080326107[30] = 0;
   out_6048005697080326107[31] = 0;
   out_6048005697080326107[32] = 0;
   out_6048005697080326107[33] = 0;
   out_6048005697080326107[34] = 0;
   out_6048005697080326107[35] = 0;
   out_6048005697080326107[36] = 0;
   out_6048005697080326107[37] = 0;
   out_6048005697080326107[38] = 0;
   out_6048005697080326107[39] = 0;
   out_6048005697080326107[40] = 0;
   out_6048005697080326107[41] = 1;
   out_6048005697080326107[42] = 0;
   out_6048005697080326107[43] = 0;
   out_6048005697080326107[44] = 0;
   out_6048005697080326107[45] = 0;
   out_6048005697080326107[46] = 0;
   out_6048005697080326107[47] = 0;
   out_6048005697080326107[48] = 0;
   out_6048005697080326107[49] = 0;
   out_6048005697080326107[50] = 0;
   out_6048005697080326107[51] = 0;
   out_6048005697080326107[52] = 0;
   out_6048005697080326107[53] = 0;
}
void h_14(double *state, double *unused, double *out_9131403806369573347) {
   out_9131403806369573347[0] = state[6];
   out_9131403806369573347[1] = state[7];
   out_9131403806369573347[2] = state[8];
}
void H_14(double *state, double *unused, double *out_6103676119001520412) {
   out_6103676119001520412[0] = 0;
   out_6103676119001520412[1] = 0;
   out_6103676119001520412[2] = 0;
   out_6103676119001520412[3] = 0;
   out_6103676119001520412[4] = 0;
   out_6103676119001520412[5] = 0;
   out_6103676119001520412[6] = 1;
   out_6103676119001520412[7] = 0;
   out_6103676119001520412[8] = 0;
   out_6103676119001520412[9] = 0;
   out_6103676119001520412[10] = 0;
   out_6103676119001520412[11] = 0;
   out_6103676119001520412[12] = 0;
   out_6103676119001520412[13] = 0;
   out_6103676119001520412[14] = 0;
   out_6103676119001520412[15] = 0;
   out_6103676119001520412[16] = 0;
   out_6103676119001520412[17] = 0;
   out_6103676119001520412[18] = 0;
   out_6103676119001520412[19] = 0;
   out_6103676119001520412[20] = 0;
   out_6103676119001520412[21] = 0;
   out_6103676119001520412[22] = 0;
   out_6103676119001520412[23] = 0;
   out_6103676119001520412[24] = 0;
   out_6103676119001520412[25] = 1;
   out_6103676119001520412[26] = 0;
   out_6103676119001520412[27] = 0;
   out_6103676119001520412[28] = 0;
   out_6103676119001520412[29] = 0;
   out_6103676119001520412[30] = 0;
   out_6103676119001520412[31] = 0;
   out_6103676119001520412[32] = 0;
   out_6103676119001520412[33] = 0;
   out_6103676119001520412[34] = 0;
   out_6103676119001520412[35] = 0;
   out_6103676119001520412[36] = 0;
   out_6103676119001520412[37] = 0;
   out_6103676119001520412[38] = 0;
   out_6103676119001520412[39] = 0;
   out_6103676119001520412[40] = 0;
   out_6103676119001520412[41] = 0;
   out_6103676119001520412[42] = 0;
   out_6103676119001520412[43] = 0;
   out_6103676119001520412[44] = 1;
   out_6103676119001520412[45] = 0;
   out_6103676119001520412[46] = 0;
   out_6103676119001520412[47] = 0;
   out_6103676119001520412[48] = 0;
   out_6103676119001520412[49] = 0;
   out_6103676119001520412[50] = 0;
   out_6103676119001520412[51] = 0;
   out_6103676119001520412[52] = 0;
   out_6103676119001520412[53] = 0;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_4, H_4, NULL, in_z, in_R, in_ea, MAHA_THRESH_4);
}
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_10, H_10, NULL, in_z, in_R, in_ea, MAHA_THRESH_10);
}
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_13, H_13, NULL, in_z, in_R, in_ea, MAHA_THRESH_13);
}
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_14, H_14, NULL, in_z, in_R, in_ea, MAHA_THRESH_14);
}
void pose_err_fun(double *nom_x, double *delta_x, double *out_7465916839184854202) {
  err_fun(nom_x, delta_x, out_7465916839184854202);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_1310847904861873779) {
  inv_err_fun(nom_x, true_x, out_1310847904861873779);
}
void pose_H_mod_fun(double *state, double *out_6607805894218821441) {
  H_mod_fun(state, out_6607805894218821441);
}
void pose_f_fun(double *state, double dt, double *out_534660845839446436) {
  f_fun(state,  dt, out_534660845839446436);
}
void pose_F_fun(double *state, double dt, double *out_384983850267682172) {
  F_fun(state,  dt, out_384983850267682172);
}
void pose_h_4(double *state, double *unused, double *out_185862018060751764) {
  h_4(state, unused, out_185862018060751764);
}
void pose_H_4(double *state, double *unused, double *out_9186464551296892708) {
  H_4(state, unused, out_9186464551296892708);
}
void pose_h_10(double *state, double *unused, double *out_4781947873589601556) {
  h_10(state, unused, out_4781947873589601556);
}
void pose_H_10(double *state, double *unused, double *out_8921185053970104970) {
  H_10(state, unused, out_8921185053970104970);
}
void pose_h_13(double *state, double *unused, double *out_4868669237854762150) {
  h_13(state, unused, out_4868669237854762150);
}
void pose_H_13(double *state, double *unused, double *out_6048005697080326107) {
  H_13(state, unused, out_6048005697080326107);
}
void pose_h_14(double *state, double *unused, double *out_9131403806369573347) {
  h_14(state, unused, out_9131403806369573347);
}
void pose_H_14(double *state, double *unused, double *out_6103676119001520412) {
  H_14(state, unused, out_6103676119001520412);
}
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
}

const EKF pose = {
  .name = "pose",
  .kinds = { 4, 10, 13, 14 },
  .feature_kinds = {  },
  .f_fun = pose_f_fun,
  .F_fun = pose_F_fun,
  .err_fun = pose_err_fun,
  .inv_err_fun = pose_inv_err_fun,
  .H_mod_fun = pose_H_mod_fun,
  .predict = pose_predict,
  .hs = {
    { 4, pose_h_4 },
    { 10, pose_h_10 },
    { 13, pose_h_13 },
    { 14, pose_h_14 },
  },
  .Hs = {
    { 4, pose_H_4 },
    { 10, pose_H_10 },
    { 13, pose_H_13 },
    { 14, pose_H_14 },
  },
  .updates = {
    { 4, pose_update_4 },
    { 10, pose_update_10 },
    { 13, pose_update_13 },
    { 14, pose_update_14 },
  },
  .Hes = {
  },
  .sets = {
  },
  .extra_routines = {
  },
};

ekf_lib_init(pose)
