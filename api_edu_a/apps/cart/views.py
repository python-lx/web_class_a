from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet
from rest_framework.permissions import IsAuthenticated
from django_redis import get_redis_connection

from course.models import Course, CourseExpire
from api_edu_a.utils import constant


class CartViewSet(ViewSet):
    """购物车相关操作"""

    # 只有登录成功的用户才可以访问此接口
    permission_classes = [IsAuthenticated]

    def add_cart(self, request):
        """
        将用户在前端提交的信息保存至购物车
        params: 用户id  课程id  勾选状态  有效期
        """
        course_id = request.data.get("course_id")
        user_id = request.user.id
        # 是否勾选
        select = True
        # 有效期
        expire = 0
        # 校验前端参数
        try:
            Course.objects.get(is_show=True, is_delete=False, pk=course_id)
        except Course.DoesNotExist:
            return Response({"message": "参数有误，课程不存在"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            # 获取数据库连接
            redis_connection = get_redis_connection("cart")
            cart_list_bytes = redis_connection.hget("cart_%s" % user_id, course_id)
            if cart_list_bytes:
                return Response({"message": "购物车已存在"})
            # 将数据保存到redis  使用redis管道
            pipeline = redis_connection.pipeline()
            # 保存的是商品的信息以及对应的有效期
            pipeline.hset("cart_%s" % user_id, course_id, expire)
            # 商品的勾选状态
            pipeline.sadd("selected_%s" % user_id, course_id)
            # 执行命令
            pipeline.execute()
            # 获取购物车中商品的总数据量
            course_len = redis_connection.hlen("cart_%s" % user_id)
        except:
            return Response({"message": "参数有误，购物车添加失败"},
                            status=status.HTTP_507_INSUFFICIENT_STORAGE)
        return Response({"message": "购物车添加成功", "cart_length": course_len})

    def list_cart(self, request):
        """展示购物车"""
        # 获取所需参数
        user_id = request.user.id
        redis_connection = get_redis_connection("cart")
        cart_list_bytes = redis_connection.hgetall("cart_%s" % user_id)
        selected_list_bytes = redis_connection.smembers("selected_%s" % user_id)
        # 获取前端所需的商品信息
        data = []
        for course_id_byte, expire_id_byte in cart_list_bytes.items():
            course_id = int(course_id_byte)
            expire_id = int(expire_id_byte)
            try:
                # 循环找到所有需要的课程信息
                course = Course.objects.get(is_show=True, pk=course_id, is_delete=False)
            except Course.DoesNotExist:
                continue
                # 将前端所需的信息返回
            data.append({
                "selected": True if course_id_byte in selected_list_bytes else False,
                "course_img": constant.IMG_SRC + course.course_img.url,
                "name": course.name,
                "real_price": course.real_price(),
                "id": course.id,
                "expire_list": course.expire_text,
                "expire_id": expire_id,
            })
        return Response(data)

    def change_select(self, request):
        """课程选中"""
        user_id = request.user.id
        course_id = request.query_params.get("course_id")
        selected = request.query_params.get("selected")
        redis_connection = get_redis_connection("cart")
        # 建立管道连接redis
        pipeline = redis_connection.pipeline()
        if selected == 'true':
            pipeline.sadd("selected_%s" % user_id, course_id)
        else:
            pipeline.srem("selected_%s" % user_id, course_id)
        pipeline.execute()
        return Response('ok')

    def delete_course(self, request):
        """删除课程"""
        user_id = request.user.id
        course_id = request.query_params.get("course_id")
        redis_connection = get_redis_connection("cart")
        pipeline = redis_connection.pipeline()
        pipeline.hdel("cart_%s" % user_id, course_id)
        pipeline.srem("selected_%s" % user_id, course_id)
        pipeline.execute()
        return Response('ok')

    def change_expire(self, request):
        """改变redis中课程有效期"""
        # 获取用户id  课程id  有效期id
        user_id = request.user.id
        expire_id = request.data.get("expire_id")
        course_id = request.data.get("course_id")
        # 查询操作的课程是否存在
        try:
            course = Course.objects.get(is_delete=False, is_show=True, pk=course_id)
            # 如果前端传递的有效期的id不是0 则修改对应课程的有效期
            if expire_id > 0:
                expire_obj = CourseExpire.objects.filter(is_show=True, is_delete=False, pk=expire_id)
                if not expire_obj:
                    raise CourseExpire.DoesNotExist("课程有效期不存在")
        except Course.DoesNotExist:
            return Response({"message": "课程信息不存在"}, status=status.HTTP_400_BAD_REQUEST)
        redis_connection = get_redis_connection("cart")
        redis_connection.hset("cart_%s" % user_id, course_id, expire_id)
        return Response({"message": "有效期切换成功"})


class CartOptionViewSet(ViewSet):
    permission_classes = [IsAuthenticated]

    def select_all(self, request):
        """全选"""
        user_id = request.user.id
        selected = request.query_params.get("selected")
        redis_connection = get_redis_connection("cart")
        pipeline = redis_connection.pipeline()
        if selected == 'false':
            cart_list_bytes = redis_connection.hgetall("cart_%s" % user_id)
            for course_id_byte, expire_id_byte in cart_list_bytes.items():
                course_id = int(course_id_byte)
                pipeline.sadd("selected_%s" % user_id, course_id)
        else:
            pipeline.delete("selected_%s" % user_id)
        pipeline.execute()
        return Response('ok')

    def check_select(self, request):
        """检查全选"""
        user_id = request.user.id
        redis_connection = get_redis_connection("cart")
        cart_list_bytes = redis_connection.hgetall("cart_%s" % user_id)
        selected_list_bytes = redis_connection.smembers("selected_%s" % user_id)
        if len(cart_list_bytes) == len(selected_list_bytes):
            return Response(True)
        else:
            return Response(False)

    def get_select_course(self, request):
        """
        获取购物车中选中的课程
        """
        user_id = request.user.id
        redis_connection = get_redis_connection("cart")
        # 获取当前登录用户的购物车数据
        cart_list = redis_connection.hgetall("cart_%s" % user_id)
        select_list = redis_connection.smembers("selected_%s" % user_id)
        # 商品总价
        total_price = 0
        data = []
        for course_id_byte, expire_id_byte in cart_list.items():
            course_id = int(course_id_byte)
            expire_id = int(expire_id_byte)
            # 判断商品是否被勾选
            if course_id_byte in select_list:
                # 获取课程的所有信息
                try:
                    course = Course.objects.get(is_delete=False, is_show=True, pk=course_id)
                except Course.DoesNotExist:
                    continue
                # 计算商品最终的总价格
                # 如果课程的有效期id大于0，则需要重新计算商品的价格，id不大于0则是永久有效
                origin_price = course.price
                expire_text = "永久有效"
                final_price = course.real_price()
                if expire_id > 0:
                    course_expire = CourseExpire.objects.get(pk=expire_id)
                    # 获取有效期对应的原价
                    origin_price = course_expire.price
                    expire_text = course_expire.expire_text
                    temp = course.price
                    course.price = origin_price
                    final_price = course.real_price()
                    course.price = temp
                # 将订单结算页的所需的数据返回
                data.append({
                    "course_img": constant.IMG_SRC + course.course_img.url,
                    "name": course.name,
                    # 最终的价格  参与过活动  有效期的价格
                    "final_price": final_price,
                    "id": course.id,
                    "expire_text": expire_text,
                    "price": origin_price
                })
                # 商品的总价
                total_price += float(final_price)
        return Response({"course_list": data, "total_price": total_price, "message": "获取成功"})
