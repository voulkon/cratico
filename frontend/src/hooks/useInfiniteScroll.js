import { useEffect, useRef } from 'react';

const useInfiniteScroll = ({
  hasMore,
  loading,
  loadingMore,
  onLoadMore,
  threshold = 0.1,
  enabled = true,
}) => {
  const sentinelRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore && !loading) {
          onLoadMore();
        }
      },
      { threshold }
    );

    const currentTarget = sentinelRef.current;
    if (currentTarget) observer.observe(currentTarget);

    return () => {
      if (currentTarget) observer.unobserve(currentTarget);
    };
  }, [enabled, hasMore, loadingMore, loading, onLoadMore, threshold]);

  return { sentinelRef };
};

export default useInfiniteScroll;
