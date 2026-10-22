// 最小冒烟文件（专门用于"先确认导入通道本身能工作"，再导正式模型）
// 期望结果：导入后出现根命名空间 SmokeTest，其下有 part def Widget 和属性 mass。
package SmokeTest {
    part def Widget {
        attribute mass : Real = 1.0;
    }
}
