import 'package:tutor_contracts/tutor_contracts.dart';

String subjectName(Subject subject) => switch (subject) {
  Subject.math => '数学',
  Subject.physics => '物理',
  Subject.chemistry => '化学',
  Subject.$unknown => '其他学科',
};

String answerModeName(AnswerMode mode) => switch (mode) {
  AnswerMode.singleChoice => '单选题',
  AnswerMode.multipleChoice => '多选题',
  AnswerMode.fill => '填空题',
  AnswerMode.written => '解答题',
  AnswerMode.experiment => '实验题',
  AnswerMode.$unknown => '题目',
};

/// 不自动评分、提交后由学生对照要点自查的题（解答题、实验题）。
bool isSubjectiveMode(AnswerMode? mode) =>
    mode == AnswerMode.written || mode == AnswerMode.experiment;

String taskKindName(TaskKind kind) => switch (kind) {
  TaskKind.newTopic => '新题',
  TaskKind.reviewMistake => '复习旧错题',
  TaskKind.retest => '间隔复测',
  TaskKind.weakPoint => '薄弱点',
  TaskKind.variant => '变式',
  TaskKind.$unknown => '任务',
};

String gradeName(Grade grade) => switch (grade) {
  Grade.g10 => '高一',
  Grade.g11 => '高二',
  Grade.g12 => '高三',
  Grade.$unknown => '未知年级',
};

String regionName(RegionCode region) => switch (region) {
  RegionCode.cn51 => '四川',
  RegionCode.cn50 => '重庆',
  RegionCode.$unknown => '未知地区',
};

/// 一道题的路由。origin：task / practice / review / variant。
String solveRoute(
  String questionId, {
  String origin = 'practice',
  String? reviewItemId,
  String? parentSessionId,
}) {
  final query = <String, String>{
    'origin': origin,
    'review': ?reviewItemId,
    'parent': ?parentSessionId,
  };
  return Uri(
    path: '/questions/$questionId/solve',
    queryParameters: query,
  ).toString();
}
