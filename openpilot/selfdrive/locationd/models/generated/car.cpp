#include "car.h"

namespace {
#define DIM 9
#define EDIM 9
#define MEDIM 9
typedef void (*Hfun)(double *, double *, double *);

double rotational_inertia;

void set_rotational_inertia(double x){ rotational_inertia = x;}

double center_to_front;

void set_center_to_front(double x){ center_to_front = x;}

double center_to_rear;

void set_center_to_rear(double x){ center_to_rear = x;}

double stiffness_front;

void set_stiffness_front(double x){ stiffness_front = x;}

double stiffness_rear;

void set_stiffness_rear(double x){ stiffness_rear = x;}
const static double MAHA_THRESH_25 = 3.8414588206941227;
const static double MAHA_THRESH_24 = 5.991464547107981;
const static double MAHA_THRESH_30 = 3.8414588206941227;
const static double MAHA_THRESH_26 = 3.8414588206941227;
const static double MAHA_THRESH_27 = 3.8414588206941227;
const static double MAHA_THRESH_29 = 3.8414588206941227;
const static double MAHA_THRESH_28 = 3.8414588206941227;
const static double MAHA_THRESH_31 = 3.8414588206941227;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_1404578713789147457) {
   out_1404578713789147457[0] = delta_x[0] + nom_x[0];
   out_1404578713789147457[1] = delta_x[1] + nom_x[1];
   out_1404578713789147457[2] = delta_x[2] + nom_x[2];
   out_1404578713789147457[3] = delta_x[3] + nom_x[3];
   out_1404578713789147457[4] = delta_x[4] + nom_x[4];
   out_1404578713789147457[5] = delta_x[5] + nom_x[5];
   out_1404578713789147457[6] = delta_x[6] + nom_x[6];
   out_1404578713789147457[7] = delta_x[7] + nom_x[7];
   out_1404578713789147457[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_4686486422632011807) {
   out_4686486422632011807[0] = -nom_x[0] + true_x[0];
   out_4686486422632011807[1] = -nom_x[1] + true_x[1];
   out_4686486422632011807[2] = -nom_x[2] + true_x[2];
   out_4686486422632011807[3] = -nom_x[3] + true_x[3];
   out_4686486422632011807[4] = -nom_x[4] + true_x[4];
   out_4686486422632011807[5] = -nom_x[5] + true_x[5];
   out_4686486422632011807[6] = -nom_x[6] + true_x[6];
   out_4686486422632011807[7] = -nom_x[7] + true_x[7];
   out_4686486422632011807[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_580044127567052722) {
   out_580044127567052722[0] = 1.0;
   out_580044127567052722[1] = 0.0;
   out_580044127567052722[2] = 0.0;
   out_580044127567052722[3] = 0.0;
   out_580044127567052722[4] = 0.0;
   out_580044127567052722[5] = 0.0;
   out_580044127567052722[6] = 0.0;
   out_580044127567052722[7] = 0.0;
   out_580044127567052722[8] = 0.0;
   out_580044127567052722[9] = 0.0;
   out_580044127567052722[10] = 1.0;
   out_580044127567052722[11] = 0.0;
   out_580044127567052722[12] = 0.0;
   out_580044127567052722[13] = 0.0;
   out_580044127567052722[14] = 0.0;
   out_580044127567052722[15] = 0.0;
   out_580044127567052722[16] = 0.0;
   out_580044127567052722[17] = 0.0;
   out_580044127567052722[18] = 0.0;
   out_580044127567052722[19] = 0.0;
   out_580044127567052722[20] = 1.0;
   out_580044127567052722[21] = 0.0;
   out_580044127567052722[22] = 0.0;
   out_580044127567052722[23] = 0.0;
   out_580044127567052722[24] = 0.0;
   out_580044127567052722[25] = 0.0;
   out_580044127567052722[26] = 0.0;
   out_580044127567052722[27] = 0.0;
   out_580044127567052722[28] = 0.0;
   out_580044127567052722[29] = 0.0;
   out_580044127567052722[30] = 1.0;
   out_580044127567052722[31] = 0.0;
   out_580044127567052722[32] = 0.0;
   out_580044127567052722[33] = 0.0;
   out_580044127567052722[34] = 0.0;
   out_580044127567052722[35] = 0.0;
   out_580044127567052722[36] = 0.0;
   out_580044127567052722[37] = 0.0;
   out_580044127567052722[38] = 0.0;
   out_580044127567052722[39] = 0.0;
   out_580044127567052722[40] = 1.0;
   out_580044127567052722[41] = 0.0;
   out_580044127567052722[42] = 0.0;
   out_580044127567052722[43] = 0.0;
   out_580044127567052722[44] = 0.0;
   out_580044127567052722[45] = 0.0;
   out_580044127567052722[46] = 0.0;
   out_580044127567052722[47] = 0.0;
   out_580044127567052722[48] = 0.0;
   out_580044127567052722[49] = 0.0;
   out_580044127567052722[50] = 1.0;
   out_580044127567052722[51] = 0.0;
   out_580044127567052722[52] = 0.0;
   out_580044127567052722[53] = 0.0;
   out_580044127567052722[54] = 0.0;
   out_580044127567052722[55] = 0.0;
   out_580044127567052722[56] = 0.0;
   out_580044127567052722[57] = 0.0;
   out_580044127567052722[58] = 0.0;
   out_580044127567052722[59] = 0.0;
   out_580044127567052722[60] = 1.0;
   out_580044127567052722[61] = 0.0;
   out_580044127567052722[62] = 0.0;
   out_580044127567052722[63] = 0.0;
   out_580044127567052722[64] = 0.0;
   out_580044127567052722[65] = 0.0;
   out_580044127567052722[66] = 0.0;
   out_580044127567052722[67] = 0.0;
   out_580044127567052722[68] = 0.0;
   out_580044127567052722[69] = 0.0;
   out_580044127567052722[70] = 1.0;
   out_580044127567052722[71] = 0.0;
   out_580044127567052722[72] = 0.0;
   out_580044127567052722[73] = 0.0;
   out_580044127567052722[74] = 0.0;
   out_580044127567052722[75] = 0.0;
   out_580044127567052722[76] = 0.0;
   out_580044127567052722[77] = 0.0;
   out_580044127567052722[78] = 0.0;
   out_580044127567052722[79] = 0.0;
   out_580044127567052722[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_2014789312445062039) {
   out_2014789312445062039[0] = state[0];
   out_2014789312445062039[1] = state[1];
   out_2014789312445062039[2] = state[2];
   out_2014789312445062039[3] = state[3];
   out_2014789312445062039[4] = state[4];
   out_2014789312445062039[5] = dt*(stiffness_front*(-state[2] - state[3] + state[7])*state[0]/state[1] + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/state[4] + ((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4])*state[6] - 9.8100000000000005*state[8]) + state[5];
   out_2014789312445062039[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_2014789312445062039[7] = state[7];
   out_2014789312445062039[8] = state[8];
}
void F_fun(double *state, double dt, double *out_4432406039518459070) {
   out_4432406039518459070[0] = 1;
   out_4432406039518459070[1] = 0;
   out_4432406039518459070[2] = 0;
   out_4432406039518459070[3] = 0;
   out_4432406039518459070[4] = 0;
   out_4432406039518459070[5] = 0;
   out_4432406039518459070[6] = 0;
   out_4432406039518459070[7] = 0;
   out_4432406039518459070[8] = 0;
   out_4432406039518459070[9] = 0;
   out_4432406039518459070[10] = 1;
   out_4432406039518459070[11] = 0;
   out_4432406039518459070[12] = 0;
   out_4432406039518459070[13] = 0;
   out_4432406039518459070[14] = 0;
   out_4432406039518459070[15] = 0;
   out_4432406039518459070[16] = 0;
   out_4432406039518459070[17] = 0;
   out_4432406039518459070[18] = 0;
   out_4432406039518459070[19] = 0;
   out_4432406039518459070[20] = 1;
   out_4432406039518459070[21] = 0;
   out_4432406039518459070[22] = 0;
   out_4432406039518459070[23] = 0;
   out_4432406039518459070[24] = 0;
   out_4432406039518459070[25] = 0;
   out_4432406039518459070[26] = 0;
   out_4432406039518459070[27] = 0;
   out_4432406039518459070[28] = 0;
   out_4432406039518459070[29] = 0;
   out_4432406039518459070[30] = 1;
   out_4432406039518459070[31] = 0;
   out_4432406039518459070[32] = 0;
   out_4432406039518459070[33] = 0;
   out_4432406039518459070[34] = 0;
   out_4432406039518459070[35] = 0;
   out_4432406039518459070[36] = 0;
   out_4432406039518459070[37] = 0;
   out_4432406039518459070[38] = 0;
   out_4432406039518459070[39] = 0;
   out_4432406039518459070[40] = 1;
   out_4432406039518459070[41] = 0;
   out_4432406039518459070[42] = 0;
   out_4432406039518459070[43] = 0;
   out_4432406039518459070[44] = 0;
   out_4432406039518459070[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/state[1] + (-stiffness_front - stiffness_rear)*state[5]/state[4] + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/state[4]);
   out_4432406039518459070[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/pow(state[1], 2);
   out_4432406039518459070[47] = -dt*stiffness_front*state[0]/state[1];
   out_4432406039518459070[48] = -dt*stiffness_front*state[0]/state[1];
   out_4432406039518459070[49] = dt*(-(-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/pow(state[4], 2) + (-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/pow(state[4], 2) - 1)*state[6]);
   out_4432406039518459070[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/state[4] + 1;
   out_4432406039518459070[51] = dt*((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4]);
   out_4432406039518459070[52] = dt*stiffness_front*state[0]/state[1];
   out_4432406039518459070[53] = -9.8100000000000005*dt;
   out_4432406039518459070[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_4432406039518459070[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_4432406039518459070[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4432406039518459070[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4432406039518459070[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_4432406039518459070[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_4432406039518459070[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_4432406039518459070[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4432406039518459070[62] = 0;
   out_4432406039518459070[63] = 0;
   out_4432406039518459070[64] = 0;
   out_4432406039518459070[65] = 0;
   out_4432406039518459070[66] = 0;
   out_4432406039518459070[67] = 0;
   out_4432406039518459070[68] = 0;
   out_4432406039518459070[69] = 0;
   out_4432406039518459070[70] = 1;
   out_4432406039518459070[71] = 0;
   out_4432406039518459070[72] = 0;
   out_4432406039518459070[73] = 0;
   out_4432406039518459070[74] = 0;
   out_4432406039518459070[75] = 0;
   out_4432406039518459070[76] = 0;
   out_4432406039518459070[77] = 0;
   out_4432406039518459070[78] = 0;
   out_4432406039518459070[79] = 0;
   out_4432406039518459070[80] = 1;
}
void h_25(double *state, double *unused, double *out_4434722456094921626) {
   out_4434722456094921626[0] = state[6];
}
void H_25(double *state, double *unused, double *out_4323647697617612118) {
   out_4323647697617612118[0] = 0;
   out_4323647697617612118[1] = 0;
   out_4323647697617612118[2] = 0;
   out_4323647697617612118[3] = 0;
   out_4323647697617612118[4] = 0;
   out_4323647697617612118[5] = 0;
   out_4323647697617612118[6] = 1;
   out_4323647697617612118[7] = 0;
   out_4323647697617612118[8] = 0;
}
void h_24(double *state, double *unused, double *out_2286200415919263266) {
   out_2286200415919263266[0] = state[4];
   out_2286200415919263266[1] = state[5];
}
void H_24(double *state, double *unused, double *out_6500862121224762091) {
   out_6500862121224762091[0] = 0;
   out_6500862121224762091[1] = 0;
   out_6500862121224762091[2] = 0;
   out_6500862121224762091[3] = 0;
   out_6500862121224762091[4] = 1;
   out_6500862121224762091[5] = 0;
   out_6500862121224762091[6] = 0;
   out_6500862121224762091[7] = 0;
   out_6500862121224762091[8] = 0;
   out_6500862121224762091[9] = 0;
   out_6500862121224762091[10] = 0;
   out_6500862121224762091[11] = 0;
   out_6500862121224762091[12] = 0;
   out_6500862121224762091[13] = 0;
   out_6500862121224762091[14] = 1;
   out_6500862121224762091[15] = 0;
   out_6500862121224762091[16] = 0;
   out_6500862121224762091[17] = 0;
}
void h_30(double *state, double *unused, double *out_797272927840899276) {
   out_797272927840899276[0] = state[4];
}
void H_30(double *state, double *unused, double *out_6841980656124860745) {
   out_6841980656124860745[0] = 0;
   out_6841980656124860745[1] = 0;
   out_6841980656124860745[2] = 0;
   out_6841980656124860745[3] = 0;
   out_6841980656124860745[4] = 1;
   out_6841980656124860745[5] = 0;
   out_6841980656124860745[6] = 0;
   out_6841980656124860745[7] = 0;
   out_6841980656124860745[8] = 0;
}
void h_26(double *state, double *unused, double *out_1807132392967798375) {
   out_1807132392967798375[0] = state[7];
}
void H_26(double *state, double *unused, double *out_582144378743555894) {
   out_582144378743555894[0] = 0;
   out_582144378743555894[1] = 0;
   out_582144378743555894[2] = 0;
   out_582144378743555894[3] = 0;
   out_582144378743555894[4] = 0;
   out_582144378743555894[5] = 0;
   out_582144378743555894[6] = 0;
   out_582144378743555894[7] = 1;
   out_582144378743555894[8] = 0;
}
void h_27(double *state, double *unused, double *out_6557551021466237620) {
   out_6557551021466237620[0] = state[3];
}
void H_27(double *state, double *unused, double *out_4667217344324435834) {
   out_4667217344324435834[0] = 0;
   out_4667217344324435834[1] = 0;
   out_4667217344324435834[2] = 0;
   out_4667217344324435834[3] = 1;
   out_4667217344324435834[4] = 0;
   out_4667217344324435834[5] = 0;
   out_4667217344324435834[6] = 0;
   out_4667217344324435834[7] = 0;
   out_4667217344324435834[8] = 0;
}
void h_29(double *state, double *unused, double *out_4204400339819946369) {
   out_4204400339819946369[0] = state[1];
}
void H_29(double *state, double *unused, double *out_7352212000439252929) {
   out_7352212000439252929[0] = 0;
   out_7352212000439252929[1] = 1;
   out_7352212000439252929[2] = 0;
   out_7352212000439252929[3] = 0;
   out_7352212000439252929[4] = 0;
   out_7352212000439252929[5] = 0;
   out_7352212000439252929[6] = 0;
   out_7352212000439252929[7] = 0;
   out_7352212000439252929[8] = 0;
}
void h_28(double *state, double *unused, double *out_8415018360440916746) {
   out_8415018360440916746[0] = state[0];
}
void H_28(double *state, double *unused, double *out_2269812983369722355) {
   out_2269812983369722355[0] = 1;
   out_2269812983369722355[1] = 0;
   out_2269812983369722355[2] = 0;
   out_2269812983369722355[3] = 0;
   out_2269812983369722355[4] = 0;
   out_2269812983369722355[5] = 0;
   out_2269812983369722355[6] = 0;
   out_2269812983369722355[7] = 0;
   out_2269812983369722355[8] = 0;
}
void h_31(double *state, double *unused, double *out_7424193691138334827) {
   out_7424193691138334827[0] = state[8];
}
void H_31(double *state, double *unused, double *out_44063723489795582) {
   out_44063723489795582[0] = 0;
   out_44063723489795582[1] = 0;
   out_44063723489795582[2] = 0;
   out_44063723489795582[3] = 0;
   out_44063723489795582[4] = 0;
   out_44063723489795582[5] = 0;
   out_44063723489795582[6] = 0;
   out_44063723489795582[7] = 0;
   out_44063723489795582[8] = 1;
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

void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_25, H_25, NULL, in_z, in_R, in_ea, MAHA_THRESH_25);
}
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<2, 3, 0>(in_x, in_P, h_24, H_24, NULL, in_z, in_R, in_ea, MAHA_THRESH_24);
}
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_30, H_30, NULL, in_z, in_R, in_ea, MAHA_THRESH_30);
}
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_26, H_26, NULL, in_z, in_R, in_ea, MAHA_THRESH_26);
}
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_27, H_27, NULL, in_z, in_R, in_ea, MAHA_THRESH_27);
}
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_29, H_29, NULL, in_z, in_R, in_ea, MAHA_THRESH_29);
}
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_28, H_28, NULL, in_z, in_R, in_ea, MAHA_THRESH_28);
}
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_31, H_31, NULL, in_z, in_R, in_ea, MAHA_THRESH_31);
}
void car_err_fun(double *nom_x, double *delta_x, double *out_1404578713789147457) {
  err_fun(nom_x, delta_x, out_1404578713789147457);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4686486422632011807) {
  inv_err_fun(nom_x, true_x, out_4686486422632011807);
}
void car_H_mod_fun(double *state, double *out_580044127567052722) {
  H_mod_fun(state, out_580044127567052722);
}
void car_f_fun(double *state, double dt, double *out_2014789312445062039) {
  f_fun(state,  dt, out_2014789312445062039);
}
void car_F_fun(double *state, double dt, double *out_4432406039518459070) {
  F_fun(state,  dt, out_4432406039518459070);
}
void car_h_25(double *state, double *unused, double *out_4434722456094921626) {
  h_25(state, unused, out_4434722456094921626);
}
void car_H_25(double *state, double *unused, double *out_4323647697617612118) {
  H_25(state, unused, out_4323647697617612118);
}
void car_h_24(double *state, double *unused, double *out_2286200415919263266) {
  h_24(state, unused, out_2286200415919263266);
}
void car_H_24(double *state, double *unused, double *out_6500862121224762091) {
  H_24(state, unused, out_6500862121224762091);
}
void car_h_30(double *state, double *unused, double *out_797272927840899276) {
  h_30(state, unused, out_797272927840899276);
}
void car_H_30(double *state, double *unused, double *out_6841980656124860745) {
  H_30(state, unused, out_6841980656124860745);
}
void car_h_26(double *state, double *unused, double *out_1807132392967798375) {
  h_26(state, unused, out_1807132392967798375);
}
void car_H_26(double *state, double *unused, double *out_582144378743555894) {
  H_26(state, unused, out_582144378743555894);
}
void car_h_27(double *state, double *unused, double *out_6557551021466237620) {
  h_27(state, unused, out_6557551021466237620);
}
void car_H_27(double *state, double *unused, double *out_4667217344324435834) {
  H_27(state, unused, out_4667217344324435834);
}
void car_h_29(double *state, double *unused, double *out_4204400339819946369) {
  h_29(state, unused, out_4204400339819946369);
}
void car_H_29(double *state, double *unused, double *out_7352212000439252929) {
  H_29(state, unused, out_7352212000439252929);
}
void car_h_28(double *state, double *unused, double *out_8415018360440916746) {
  h_28(state, unused, out_8415018360440916746);
}
void car_H_28(double *state, double *unused, double *out_2269812983369722355) {
  H_28(state, unused, out_2269812983369722355);
}
void car_h_31(double *state, double *unused, double *out_7424193691138334827) {
  h_31(state, unused, out_7424193691138334827);
}
void car_H_31(double *state, double *unused, double *out_44063723489795582) {
  H_31(state, unused, out_44063723489795582);
}
void car_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
void car_set_rotational_inertia(double x) {
  set_rotational_inertia(x);
}
void car_set_center_to_front(double x) {
  set_center_to_front(x);
}
void car_set_center_to_rear(double x) {
  set_center_to_rear(x);
}
void car_set_stiffness_front(double x) {
  set_stiffness_front(x);
}
void car_set_stiffness_rear(double x) {
  set_stiffness_rear(x);
}
}

const EKF car = {
  .name = "car",
  .kinds = { 25, 24, 30, 26, 27, 29, 28, 31 },
  .feature_kinds = {  },
  .f_fun = car_f_fun,
  .F_fun = car_F_fun,
  .err_fun = car_err_fun,
  .inv_err_fun = car_inv_err_fun,
  .H_mod_fun = car_H_mod_fun,
  .predict = car_predict,
  .hs = {
    { 25, car_h_25 },
    { 24, car_h_24 },
    { 30, car_h_30 },
    { 26, car_h_26 },
    { 27, car_h_27 },
    { 29, car_h_29 },
    { 28, car_h_28 },
    { 31, car_h_31 },
  },
  .Hs = {
    { 25, car_H_25 },
    { 24, car_H_24 },
    { 30, car_H_30 },
    { 26, car_H_26 },
    { 27, car_H_27 },
    { 29, car_H_29 },
    { 28, car_H_28 },
    { 31, car_H_31 },
  },
  .updates = {
    { 25, car_update_25 },
    { 24, car_update_24 },
    { 30, car_update_30 },
    { 26, car_update_26 },
    { 27, car_update_27 },
    { 29, car_update_29 },
    { 28, car_update_28 },
    { 31, car_update_31 },
  },
  .Hes = {
  },
  .sets = {
    { "rotational_inertia", car_set_rotational_inertia },
    { "center_to_front", car_set_center_to_front },
    { "center_to_rear", car_set_center_to_rear },
    { "stiffness_front", car_set_stiffness_front },
    { "stiffness_rear", car_set_stiffness_rear },
  },
  .extra_routines = {
  },
};

ekf_lib_init(car)
